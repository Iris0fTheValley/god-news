from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str, *, sqlite_busy_timeout_ms: int = 5_000) -> None:
        self._sqlite_busy_timeout_ms = sqlite_busy_timeout_ms
        self._ensure_sqlite_parent(url)
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
        )
        if make_url(url).drivername.startswith("sqlite"):
            self._configure_sqlite()
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            del connection_record
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={self._sqlite_busy_timeout_ms}")
                cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

    @staticmethod
    def _ensure_sqlite_parent(url: str) -> None:
        parsed = make_url(url)
        if not parsed.drivername.startswith("sqlite") or not parsed.database:
            return
        if parsed.database == ":memory:":
            return
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    async def create_schema(self) -> None:
        # Importing registers ORM tables on Base.metadata.
        from god_news.infrastructure import repositories as _repositories  # noqa: F401
        from god_news.infrastructure import role_profiles as _role_profiles  # noqa: F401
        from god_news.infrastructure import source_media_repository as _source_media  # noqa: F401
        from god_news.infrastructure import source_runs as _source_runs  # noqa: F401
        from god_news.infrastructure import source_schedule as _source_schedule  # noqa: F401
        from god_news.infrastructure import video_repository as _video_repository  # noqa: F401
        from god_news.infrastructure import visual_repository as _visual_repository  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await self._apply_story_sqlite_additive_migrations(connection)
            await self._apply_sqlite_additive_migrations(connection)
            await self._migrate_legacy_pending_tts_records(connection)
            await self._migrate_legacy_story_emotions(connection)

    @staticmethod
    async def _apply_story_sqlite_additive_migrations(connection: AsyncConnection) -> None:
        """Keep the local SQLite development database forward-compatible.

        The project intentionally has no migration runner yet.  This narrow,
        idempotent migration only adds the nullable editorial-title column that
        existing installations need for the story PATCH contract.
        """

        if connection.dialect.name != "sqlite":
            return

        column_names = {
            column["name"]
            for column in await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns("stories")
            )
        }
        if "title" not in column_names:
            await connection.execute(text("ALTER TABLE stories ADD COLUMN title VARCHAR(500)"))

    @staticmethod
    async def _apply_sqlite_additive_migrations(connection: AsyncConnection) -> None:
        """Apply only backward-compatible SQLite schema additions.

        ``metadata.create_all`` intentionally does not alter an already-created
        table. These role fields therefore need an explicit additive migration
        for existing local installations. Legacy rows remain non-TTS until an
        operator explicitly completes their multi-emotion voice configuration.
        The fixed definitions and column check make repeated application
        idempotent.
        """

        if connection.dialect.name != "sqlite":
            return

        result = await connection.exec_driver_sql("PRAGMA table_info(role_profiles)")
        existing_columns = {str(row[1]) for row in result.all()}
        additions = {
            "gpt_weights_path": "TEXT NULL",
            "sovits_weights_path": "TEXT NULL",
            "tts_model_profile": "TEXT NULL",
            "reference_language": "TEXT NULL",
            "default_spoken_language": "TEXT NOT NULL DEFAULT 'zh-CN'",
            "character_prompt": "TEXT NOT NULL DEFAULT ''",
            "emotion_refs_json": "TEXT NOT NULL DEFAULT '{}'",
            "tts_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        }
        for column_name, definition in additions.items():
            if column_name not in existing_columns:
                await connection.exec_driver_sql(
                    f"ALTER TABLE role_profiles ADD COLUMN {column_name} {definition}"
                )
        # Disabled profiles may retain historical speaker ids, while active
        # lookup stays deterministic. A migration must not guess which of two
        # duplicate enabled records wins, so surface an actionable diagnosis
        # before SQLite's index error obscures the offending values.
        duplicate_rows = (
            await connection.exec_driver_sql(
                "SELECT speaker_id FROM role_profiles WHERE enabled = 1 "
                "GROUP BY speaker_id HAVING COUNT(*) > 1 ORDER BY speaker_id LIMIT 10"
            )
        ).all()
        if duplicate_rows:
            speaker_ids = ", ".join(str(row[0]) for row in duplicate_rows)
            raise RuntimeError(
                "Cannot apply deterministic enabled-speaker uniqueness: duplicate enabled "
                f"speaker_id values require manual resolution ({speaker_ids})."
            )
        await connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_role_profiles_enabled_speaker_id "
            "ON role_profiles(speaker_id) WHERE enabled = 1"
        )

    @staticmethod
    async def _migrate_legacy_pending_tts_records(connection: AsyncConnection) -> None:
        """Move pre-workflow-rebuild retry records to the explicit TTS gate.

        Before the script-review/manual-TTS workflow, a failed re-synthesis
        could leave a story at ``PENDING_SECOND_REVIEW`` without audio. That
        state is no longer actionable: final review needs audio, and TTS only
        starts from ``PENDING_TTS``. Preserve the script and failure evidence,
        but make the retry explicit and append an audit transition. The update
        is intentionally idempotent because the status changes on first run.
        """

        if connection.dialect.name != "sqlite":
            return

        legacy_rows = (
            await connection.execute(
                text(
                    "SELECT story_id, version FROM stories "
                    "WHERE status = :status AND script_json IS NOT NULL AND audio_json IS NULL"
                ),
                {"status": "PENDING_SECOND_REVIEW"},
            )
        ).mappings().all()
        if not legacy_rows:
            return

        migrated_at = datetime.now(UTC)
        for row in legacy_rows:
            story_id = str(row["story_id"])
            expected_version = int(row["version"])
            result = await connection.execute(
                text(
                    "UPDATE stories SET status = :target_status, version = version + 1, "
                    "updated_at = :updated_at "
                    "WHERE story_id = :story_id AND status = :source_status AND version = :version"
                ),
                {
                    "target_status": "PENDING_TTS",
                    "updated_at": migrated_at,
                    "story_id": story_id,
                    "source_status": "PENDING_SECOND_REVIEW",
                    "version": expected_version,
                },
            )
            if result.rowcount != 1:
                continue
            await connection.execute(
                text(
                    "INSERT INTO state_transitions "
                    "(transition_id, story_id, from_status, to_status, reason, occurred_at) "
                    "VALUES (:transition_id, :story_id, :from_status, :to_status, :reason, "
                    ":occurred_at)"
                ),
                {
                    "transition_id": str(uuid4()),
                    "story_id": story_id,
                    "from_status": "PENDING_SECOND_REVIEW",
                    "to_status": "PENDING_TTS",
                    "reason": "workflow migration: legacy failed TTS moved to manual retry gate",
                    "occurred_at": migrated_at,
                },
            )

    @staticmethod
    async def _migrate_legacy_story_emotions(connection: AsyncConnection) -> None:
        """Canonicalize old free-form emotions before typed story deserialization.

        The former script contract accepted arbitrary strings.  New API input
        is deliberately limited to the seven reference-voice labels, but an
        upgrade must not make an older local database unreadable.  This
        migration runs only on persisted story JSON, maps an obsolete or
        unknown label to the conservative default ``happiness``, increments
        the optimistic-lock version, and records the original labels in the
        existing durable transition audit.  Live requests still receive normal
        Pydantic validation; this is an upgrade compatibility boundary, not an
        input leniency rule.
        """

        if connection.dialect.name != "sqlite":
            return

        rows = (
            await connection.execute(
                text(
                    "SELECT story_id, status, preferences_json, script_json, audio_json "
                    "FROM stories"
                )
            )
        ).mappings().all()
        now = datetime.now(UTC)
        for row in rows:
            preferences, preference_changes = Database._normalize_emotions_in_payload(
                row["preferences_json"],
                path="preferences",
            )
            script, script_changes = Database._normalize_emotions_in_payload(
                row["script_json"],
                path="script",
            )
            audio, audio_changes = Database._normalize_emotions_in_payload(
                row["audio_json"],
                path="audio",
            )
            changes = preference_changes + script_changes + audio_changes
            if not changes:
                continue
            story_id = str(row["story_id"])
            await connection.execute(
                text(
                    "UPDATE stories SET preferences_json = :preferences, script_json = :script, "
                    "audio_json = :audio, version = version + 1, updated_at = :updated_at "
                    "WHERE story_id = :story_id"
                ),
                {
                    "preferences": preferences,
                    "script": script,
                    "audio": audio,
                    "updated_at": now,
                    "story_id": story_id,
                },
            )
            original_labels = ", ".join(changes)
            reason = (
                "schema migration: normalized legacy speech emotion labels to happiness "
                f"({original_labels})"
            )
            await connection.execute(
                text(
                    "INSERT INTO state_transitions "
                    "(transition_id, story_id, from_status, to_status, reason, occurred_at) "
                    "VALUES (:transition_id, :story_id, :from_status, :to_status, :reason, "
                    ":occurred_at)"
                ),
                {
                    "transition_id": str(uuid4()),
                    "story_id": story_id,
                    "from_status": str(row["status"]),
                    "to_status": str(row["status"]),
                    "reason": reason[:300],
                    "occurred_at": now,
                },
            )

    @staticmethod
    def _normalize_emotions_in_payload(
        serialized: object,
        *,
        path: str,
    ) -> tuple[str | None, list[str]]:
        """Return canonical JSON plus an audit list of changed ``path=value`` labels."""

        if serialized is None:
            return None, []
        if not isinstance(serialized, str):
            raise RuntimeError(f"Cannot migrate non-text {path} JSON in stories table.")
        try:
            payload = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Cannot migrate malformed {path} JSON in stories table.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Cannot migrate non-object {path} JSON in stories table.")

        changes: list[str] = []

        def canonicalize(container: object, *, location: str) -> None:
            if not isinstance(container, dict) or "emotion" not in container:
                return
            raw = container["emotion"]
            normalized = raw.strip().casefold() if isinstance(raw, str) else ""
            if normalized in {
                "happiness",
                "sadness",
                "anger",
                "disgust",
                "like",
                "surprise",
                "fear",
            }:
                canonical = normalized
            else:
                canonical = "happiness"
            if raw != canonical:
                changes.append(f"{location}={raw!r}")
                container["emotion"] = canonical

        if path == "preferences":
            canonicalize(payload, location=path)
        elif path == "script":
            segments = payload.get("segments")
            if isinstance(segments, list):
                for index, segment in enumerate(segments):
                    canonicalize(segment, location=f"script.segments[{index}]")
        elif path == "audio":
            synthesis = payload.get("synthesis")
            if isinstance(synthesis, dict):
                provenance = synthesis.get("segment_provenance")
                if isinstance(provenance, list):
                    for index, entry in enumerate(provenance):
                        canonicalize(
                            entry,
                            location=f"audio.synthesis.segment_provenance[{index}]",
                        )
        else:
            raise RuntimeError(f"Unsupported story JSON migration path '{path}'.")

        if not changes:
            return serialized, []
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), changes

    async def healthcheck(self) -> None:
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self.engine.dispose()
