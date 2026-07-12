from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from god_news.api.app import create_app
from god_news.infrastructure.database import Database
from god_news.infrastructure.role_profiles import (
    InMemoryRoleProfileRepository,
    SqlAlchemyRoleProfileRepository,
)
from god_news.logging import reset_trace_id, set_trace_id
from god_news.operations.errors import RoleProfileConflictError
from god_news.operations.models import (
    OperationRunStatus,
    RetentionAction,
    RetentionCleanupCommand,
    RoleKind,
    RoleProfileCreate,
    RoleProfileReplace,
    TriggerOrigin,
)
from god_news.operations.retention import RetentionCleanupHandler
from god_news.operations.roles import RoleProfileService
from god_news.operations.scheduler import IntervalScheduler, OperationDispatcher

from .conftest import Stack


def _role(slug: str = "main-host") -> RoleProfileCreate:
    return RoleProfileCreate(
        slug=slug,
        display_name="Main host",
        kind=RoleKind.HOST,
        speaker_id="voice-main",
        default_emotion="warm",
        gpt_weights_path=r"J:\models\gpt-narrator.pth",
        sovits_weights_path=r"J:\models\sovits-narrator.pth",
        visual_assets={
            "live2d_asset_ref": "roles/main/model3.json",
            "differential_art": [
                {
                    "state_id": "warm",
                    "asset_ref": "roles/main/warm.webp",
                    "emotion": "warm",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_sql_role_profiles_support_versioned_crud(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'roles.db').as_posix()}")
    await database.create_schema()
    service = RoleProfileService(SqlAlchemyRoleProfileRepository(database.sessions))
    try:
        created = await service.create(_role())
        assert created.version == 1
        assert created.visual_assets.live2d_asset_ref == "roles/main/model3.json"
        assert created.gpt_weights_path == r"J:\models\gpt-narrator.pth"
        assert created.sovits_weights_path == r"J:\models\sovits-narrator.pth"

        replacement_values = _role().model_dump()
        replacement_values["display_name"] = "Updated host"
        replacement_values["gpt_weights_path"] = "weights/updated-gpt.ckpt"
        replacement = RoleProfileReplace(
            **replacement_values,
            expected_version=created.version,
        )
        updated = await service.replace(created.profile_id, replacement)
        assert updated.version == 2
        assert updated.display_name == "Updated host"
        assert updated.gpt_weights_path == "weights/updated-gpt.ckpt"
        assert updated.sovits_weights_path == r"J:\models\sovits-narrator.pth"

        with pytest.raises(RoleProfileConflictError):
            await service.replace(created.profile_id, replacement)
        with pytest.raises(RoleProfileConflictError, match="slug"):
            await service.create(_role())

        enabled_profiles = await service.list(enabled=True)
        assert [profile.profile_id for profile in enabled_profiles] == [created.profile_id]
        disabled = await service.delete(created.profile_id, expected_version=updated.version)
        assert disabled.enabled is False
        assert disabled.version == 3
        persisted = await service.get(created.profile_id)
        assert persisted.gpt_weights_path == "weights/updated-gpt.ckpt"
        assert await service.list(enabled=True) == []
        disabled_profiles = await service.list(enabled=False)
        assert [profile.profile_id for profile in disabled_profiles] == [created.profile_id]
        with pytest.raises(RoleProfileConflictError):
            await service.delete(created.profile_id, expected_version=updated.version)
        disabled_again = await service.delete(created.profile_id, expected_version=disabled.version)
        assert disabled_again == disabled
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_sqlite_role_weight_migration_is_additive_and_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-roles.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE role_profiles (
                profile_id VARCHAR(36) PRIMARY KEY NOT NULL,
                slug VARCHAR(64) NOT NULL UNIQUE,
                display_name VARCHAR(200) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                speaker_id VARCHAR(200) NOT NULL,
                default_emotion VARCHAR(100) NOT NULL,
                default_speed FLOAT NOT NULL,
                default_pitch FLOAT NOT NULL,
                visual_assets_json TEXT NOT NULL,
                enabled BOOLEAN NOT NULL,
                version INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            INSERT INTO role_profiles (
                profile_id, slug, display_name, kind, speaker_id,
                default_emotion, default_speed, default_pitch,
                visual_assets_json, enabled, version, created_at, updated_at
            ) VALUES (
                '717bf5e5-b77b-44be-852f-4e25a819befe', 'legacy-host', 'Legacy host',
                'host', 'legacy-voice', 'neutral', 1.0, 0.0,
                '{"live2d_asset_ref":null,"differential_art":[]}', 1, 1,
                '2026-07-12 00:00:00.000000', '2026-07-12 00:00:00.000000'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    database = Database(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        await database.create_schema()
        await database.create_schema()
        async with database.engine.connect() as db_connection:
            columns = (
                await db_connection.exec_driver_sql("PRAGMA table_info(role_profiles)")
            ).all()
            profile = (
                await db_connection.exec_driver_sql(
                    "SELECT slug, display_name, gpt_weights_path, sovits_weights_path "
                    "FROM role_profiles WHERE slug = 'legacy-host'"
                )
            ).one()
    finally:
        await database.aclose()

    assert {str(column[1]) for column in columns} >= {
        "gpt_weights_path",
        "sovits_weights_path",
    }
    assert tuple(profile) == ("legacy-host", "Legacy host", None, None)


def test_role_weight_asset_refs_are_inert_and_path_safe() -> None:
    role = _role()
    assert role.gpt_weights_path == r"J:\models\gpt-narrator.pth"

    invalid_values = _role().model_dump()
    invalid_values["gpt_weights_path"] = r"..\private\weights.pth"
    with pytest.raises(ValidationError, match="parent-directory traversal"):
        RoleProfileCreate.model_validate(invalid_values)

    with pytest.raises(ValidationError, match="control characters"):
        RoleProfileCreate(
            slug="safe-ref",
            display_name="Safe reference",
            kind=RoleKind.NARRATOR,
            speaker_id="voice-safe",
            gpt_weights_path="weights/unsafe\x00.pth",
        )


def _make_old(path: Path, payload: bytes = b"old") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    timestamp = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(path, (timestamp, timestamp))


@pytest.mark.asyncio
async def test_retention_is_path_scoped_and_dry_run_first(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    old_audio = media_root / "story" / "old.wav"
    new_audio = media_root / "story" / "new.wav"
    ignored_media = media_root / "story" / "notes.txt"
    old_upload = upload_root / "old.mp4"
    new_upload = upload_root / "new.mp4"
    ignored_upload = upload_root / "old.mov"
    for path in (old_audio, ignored_media, old_upload, ignored_upload):
        _make_old(path)
    new_audio.parent.mkdir(parents=True, exist_ok=True)
    new_audio.write_bytes(b"new")
    new_upload.parent.mkdir(parents=True, exist_ok=True)
    new_upload.write_bytes(b"new")

    handler = RetentionCleanupHandler(
        media_root=media_root,
        uploaded_mp4_root=upload_root,
        media_retention_days=7,
        uploaded_mp4_retention_days=3,
        media_extensions=(".wav",),
    )
    dry_run = await handler.execute(
        RetentionCleanupCommand(dry_run=True, requested_by="test-editor")
    )
    assert dry_run.eligible_count == 2
    assert dry_run.deleted_count == 0
    assert {item.action for item in dry_run.items} == {RetentionAction.WOULD_DELETE}
    assert old_audio.exists() and old_upload.exists()

    applied = await handler.execute(
        RetentionCleanupCommand(dry_run=False, requested_by="test-editor")
    )
    assert applied.deleted_count == 2
    assert applied.reclaimed_bytes == 6
    assert not old_audio.exists() and not old_upload.exists()
    assert new_audio.exists() and new_upload.exists()
    assert ignored_media.exists() and ignored_upload.exists()


@pytest.mark.asyncio
async def test_retention_preserves_assets_claimed_by_active_video_batch(tmp_path: Path) -> None:
    class Protector:
        async def protected_asset_paths(self) -> list[Path]:
            return [protected]

    media_root = tmp_path / "media"
    upload_root = tmp_path / "uploads"
    protected = media_root / "story" / "claimed.wav"
    disposable = media_root / "story" / "unclaimed.wav"
    _make_old(protected)
    _make_old(disposable)
    handler = RetentionCleanupHandler(
        media_root=media_root,
        uploaded_mp4_root=upload_root,
        media_retention_days=7,
        uploaded_mp4_retention_days=3,
        media_extensions=(".wav",),
        asset_protector=Protector(),
    )

    report = await handler.execute(
        RetentionCleanupCommand(dry_run=False, requested_by="test-editor")
    )
    assert protected.exists()
    assert not disposable.exists()
    protected_result = next(
        item for item in report.items if item.relative_path.endswith("claimed.wav")
    )
    assert protected_result.action is RetentionAction.SKIPPED
    assert protected_result.reason == "Asset is claimed by an active video batch."


@pytest.mark.asyncio
async def test_manual_and_scheduled_triggers_share_dispatcher(tmp_path: Path) -> None:
    handler = RetentionCleanupHandler(
        media_root=tmp_path / "media",
        uploaded_mp4_root=tmp_path / "uploads",
        media_retention_days=7,
        uploaded_mp4_retention_days=3,
        media_extensions=(".wav",),
    )
    dispatcher = OperationDispatcher([handler], history_limit=5)
    expected_trace_id = "d72dd94a-589a-4923-93c5-3224c68322d4"
    token = set_trace_id(expected_trace_id)
    try:
        manual = await dispatcher.trigger(
            RetentionCleanupCommand(dry_run=True, requested_by="operator"),
            origin=TriggerOrigin.MANUAL,
        )
    finally:
        reset_trace_id(token)
    assert str(manual.trace_id) == expected_trace_id
    assert manual.status is OperationRunStatus.SUCCEEDED
    assert manual.origin is TriggerOrigin.MANUAL

    scheduler = IntervalScheduler(
        dispatcher,
        enabled=True,
        interval_seconds=60,
        poll_interval_seconds=1,
        retention_dry_run=True,
    )
    schedule = (await scheduler.list_schedules())[0]
    assert schedule.next_run_at is not None
    scheduled = await scheduler.run_due(now=schedule.next_run_at + timedelta(seconds=1))
    assert scheduled is not None
    assert scheduled.origin is TriggerOrigin.SCHEDULE
    assert scheduled.schedule_id == "retention-cleanup"
    updated = (await scheduler.list_schedules())[0]
    assert updated.last_run_id == scheduled.run_id


@pytest.mark.asyncio
async def test_operations_api_exposes_roles_and_safe_cleanup(stack: Stack, tmp_path: Path) -> None:
    role_service = RoleProfileService(InMemoryRoleProfileRepository())
    handler = RetentionCleanupHandler(
        media_root=tmp_path / "media",
        uploaded_mp4_root=tmp_path / "uploads",
        media_retention_days=7,
        uploaded_mp4_retention_days=3,
        media_extensions=(".wav",),
    )
    stack.container.role_profiles = role_service
    stack.container.operations = OperationDispatcher([handler])

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/v1/roles", json=_role().model_dump(mode="json"))
            assert created.status_code == 201
            role = created.json()
            assert role["kind"] == "host"
            assert role["gpt_weights_path"] == r"J:\models\gpt-narrator.pth"
            assert role["sovits_weights_path"] == r"J:\models\sovits-narrator.pth"

            listed = await client.get("/api/v1/roles", params={"enabled": True})
            assert [item["profile_id"] for item in listed.json()] == [role["profile_id"]]

            cleanup = await client.post(
                "/api/v1/operations/retention/runs",
                json={"dry_run": True, "requested_by": "api-editor"},
            )
            assert cleanup.status_code == 200
            assert cleanup.json()["status"] == "succeeded"
            assert cleanup.json()["result"]["dry_run"] is True

            deleted = await client.request(
                "DELETE",
                f"/api/v1/roles/{role['profile_id']}",
                json={"expected_version": role["version"]},
            )
            assert deleted.status_code == 200
            disabled = deleted.json()
            assert disabled["enabled"] is False
            assert disabled["version"] == role["version"] + 1

            listed_enabled = await client.get("/api/v1/roles", params={"enabled": True})
            assert listed_enabled.status_code == 200
            assert listed_enabled.json() == []
            listed_disabled = await client.get("/api/v1/roles", params={"enabled": False})
            assert [item["profile_id"] for item in listed_disabled.json()] == [role["profile_id"]]
