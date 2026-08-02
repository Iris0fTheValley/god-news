from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.media_catalog import (
    MediaAssetUsage,
    MediaCatalogEntry,
    MediaCatalogKind,
    MediaCatalogLifecycle,
    MediaCatalogSourceKind,
    MediaUsagePurpose,
    MediaUsageState,
    make_catalog_id,
)
from god_news.domain.models import ScriptDocument
from god_news.domain.source_media import StoredSourceMediaArtifact
from god_news.domain.video import VideoBatch
from god_news.domain.visual_assets import VisualAssetOrigin
from god_news.domain.visual_discovery import (
    CommonsMediaKind,
    VisualDiscoveryStatus,
)
from god_news.errors import (
    ConcurrentMediaCatalogWriteError,
    MediaCatalogConflictError,
    MediaCatalogNotFoundError,
)
from god_news.infrastructure.database import Base
from god_news.infrastructure.repositories import StoryRow
from god_news.infrastructure.source_media_repository import SourceMediaArtifactRow
from god_news.infrastructure.video_repository import VideoBatchRow
from god_news.infrastructure.visual_discovery_repository import (
    VisualDiscoveryAssetRow,
)
from god_news.infrastructure.visual_discovery_repository import (
    _to_model as _to_discovery_asset,
)
from god_news.infrastructure.visual_repository import VisualAssetRow


class MediaCatalogLifecycleRow(Base):
    __tablename__ = "media_catalog_lifecycle"

    catalog_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaCatalogEventRow(Base):
    __tablename__ = "media_catalog_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlAlchemyMediaCatalogRepository:
    """Global read model over immutable media sources plus a lifecycle overlay."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        visual_root: Path,
        discovery_root: Path,
        source_media_root: Path,
    ) -> None:
        self._sessions = sessions
        self._roots = {
            MediaCatalogSourceKind.VISUAL_ASSET: visual_root.expanduser().resolve(strict=False),
            MediaCatalogSourceKind.VISUAL_DISCOVERY: discovery_root.expanduser().resolve(
                strict=False
            ),
            MediaCatalogSourceKind.SOURCE_MEDIA: source_media_root.expanduser().resolve(
                strict=False
            ),
        }

    async def list_entries(self) -> Sequence[MediaCatalogEntry]:
        async with self._sessions() as session:
            visual_rows = (await session.scalars(select(VisualAssetRow))).all()
            discovery_rows = (await session.scalars(select(VisualDiscoveryAssetRow))).all()
            source_rows = (await session.scalars(select(SourceMediaArtifactRow))).all()
            story_rows = {
                row.story_id: row for row in (await session.scalars(select(StoryRow))).all()
            }
            lifecycle_rows = {
                row.catalog_id: row
                for row in (await session.scalars(select(MediaCatalogLifecycleRow))).all()
            }
            batch_payloads = (
                await session.scalars(
                    select(VideoBatchRow.batch_json).order_by(VideoBatchRow.created_at.desc())
                )
            ).all()

        usage_map = self._batch_usages(batch_payloads)
        entries: list[MediaCatalogEntry] = []
        for visual_row in visual_rows:
            source_kind = MediaCatalogSourceKind.VISUAL_ASSET
            asset_id = UUID(visual_row.asset_id)
            catalog_id = make_catalog_id(source_kind, asset_id)
            usages = self._story_usages_for_visual(
                visual_row,
                story_rows.get(visual_row.story_id),
            )
            usages.extend(usage_map.get(catalog_id, ()))
            lifecycle = lifecycle_rows.get(catalog_id)
            entries.append(
                MediaCatalogEntry(
                    catalog_id=catalog_id,
                    source_kind=source_kind,
                    source_asset_id=asset_id,
                    media_kind=MediaCatalogKind.IMAGE,
                    lifecycle=self._lifecycle(lifecycle),
                    lifecycle_version=lifecycle.version if lifecycle is not None else 1,
                    story_id=UUID(visual_row.story_id),
                    segment_id=UUID(visual_row.segment_id) if visual_row.segment_id else None,
                    script_revision=visual_row.script_revision,
                    filename=visual_row.filename,
                    mime_type=visual_row.content_type,
                    sha256=visual_row.sha256,
                    size_bytes=visual_row.size_bytes,
                    has_local_content=True,
                    editorial_state="bound",
                    publish_eligible=True,
                    selectable=self._lifecycle(lifecycle) is MediaCatalogLifecycle.ACTIVE,
                    reusable=False,
                    archived_at=_aware(lifecycle.archived_at) if lifecycle else None,
                    archived_by=lifecycle.archived_by if lifecycle else None,
                    archive_reason=lifecycle.archive_reason if lifecycle else None,
                    usages=usages[:100],
                )
            )
        for discovery_row in discovery_rows:
            asset = _to_discovery_asset(discovery_row)
            candidate = asset.candidate
            source_kind = MediaCatalogSourceKind.VISUAL_DISCOVERY
            catalog_id = make_catalog_id(source_kind, asset.asset_id)
            lifecycle = lifecycle_rows.get(catalog_id)
            usages = [
                MediaAssetUsage(
                    purpose=MediaUsagePurpose.STORY_SEGMENT,
                    state=self._story_usage_state(
                        story_rows.get(str(asset.story_id)),
                        script_revision=asset.script_revision,
                        segment_id=asset.segment_id,
                    ),
                    story_id=asset.story_id,
                    segment_id=asset.segment_id,
                    script_revision=asset.script_revision,
                )
            ]
            usages.extend(usage_map.get(catalog_id, ()))
            entries.append(
                MediaCatalogEntry(
                    catalog_id=catalog_id,
                    source_kind=source_kind,
                    source_asset_id=asset.asset_id,
                    media_kind=(
                        MediaCatalogKind.IMAGE
                        if candidate.kind is CommonsMediaKind.IMAGE
                        else MediaCatalogKind.VIDEO
                    ),
                    lifecycle=self._lifecycle(lifecycle),
                    lifecycle_version=lifecycle.version if lifecycle is not None else 1,
                    story_id=asset.story_id,
                    segment_id=asset.segment_id,
                    script_revision=asset.script_revision,
                    filename=candidate.file_title.removeprefix("File:"),
                    mime_type=candidate.mime_type,
                    sha256=asset.sha256,
                    size_bytes=asset.downloaded_size_bytes,
                    width=candidate.width,
                    height=candidate.height,
                    duration_ms=asset.probed_duration_ms,
                    source_url=str(candidate.canonical_page_url),
                    external_preview_url=(
                        str(candidate.direct_download_url)
                        if asset.storage_key is None
                        else None
                    ),
                    has_local_content=asset.storage_key is not None,
                    attribution=candidate.attribution.attribution_text,
                    license_label=(
                        candidate.rights.source_license_label
                        or candidate.rights.license.value
                    ),
                    editorial_state=asset.status.value,
                    publish_eligible=(
                        asset.status is VisualDiscoveryStatus.APPROVED
                        and candidate.publish_eligible
                    ),
                    selectable=(
                        self._lifecycle(lifecycle) is MediaCatalogLifecycle.ACTIVE
                        and asset.status is VisualDiscoveryStatus.APPROVED
                        and candidate.publish_eligible
                    ),
                    reusable=(
                        self._lifecycle(lifecycle) is MediaCatalogLifecycle.ACTIVE
                        and
                        asset.status is VisualDiscoveryStatus.APPROVED
                        and candidate.publish_eligible
                    ),
                    archived_at=_aware(lifecycle.archived_at) if lifecycle else None,
                    archived_by=lifecycle.archived_by if lifecycle else None,
                    archive_reason=lifecycle.archive_reason if lifecycle else None,
                    usages=usages[:100],
                )
            )
        for source_row in source_rows:
            artifact = StoredSourceMediaArtifact.model_validate_json(source_row.artifact_json)
            source_kind = MediaCatalogSourceKind.SOURCE_MEDIA
            catalog_id = make_catalog_id(source_kind, artifact.artifact_id)
            lifecycle = lifecycle_rows.get(catalog_id)
            usages = [
                MediaAssetUsage(
                    purpose=MediaUsagePurpose.STORY_EVIDENCE,
                    state=(
                        MediaUsageState.ACTIVE
                        if self._story_is_active(story_rows.get(str(artifact.story_id)))
                        else MediaUsageState.FROZEN
                    ),
                    story_id=artifact.story_id,
                )
            ]
            usages.extend(usage_map.get(catalog_id, ()))
            entries.append(
                MediaCatalogEntry(
                    catalog_id=catalog_id,
                    source_kind=source_kind,
                    source_asset_id=artifact.artifact_id,
                    media_kind=MediaCatalogKind.VIDEO,
                    lifecycle=self._lifecycle(lifecycle),
                    lifecycle_version=lifecycle.version if lifecycle is not None else 1,
                    story_id=artifact.story_id,
                    filename=artifact.filename,
                    mime_type=artifact.content_type,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    width=artifact.probe.width,
                    height=artifact.probe.height,
                    duration_ms=artifact.probe.duration_ms,
                    source_url=str(artifact.source_url),
                    has_local_content=True,
                    attribution=artifact.attribution.attribution_text,
                    license_label=(
                        artifact.rights.license_name or artifact.rights.status
                    ),
                    editorial_state=(
                        "publish_eligible" if artifact.publish_eligible else "rights_review"
                    ),
                    publish_eligible=artifact.publish_eligible,
                    selectable=(
                        self._lifecycle(lifecycle) is MediaCatalogLifecycle.ACTIVE
                        and artifact.publish_eligible
                    ),
                    reusable=False,
                    archived_at=_aware(lifecycle.archived_at) if lifecycle else None,
                    archived_by=lifecycle.archived_by if lifecycle else None,
                    archive_reason=lifecycle.archive_reason if lifecycle else None,
                    usages=usages[:100],
                )
            )
        return sorted(entries, key=lambda item: (item.filename.casefold(), item.catalog_id))

    async def get_entry(self, catalog_id: str) -> MediaCatalogEntry:
        entry = next(
            (item for item in await self.list_entries() if item.catalog_id == catalog_id),
            None,
        )
        if entry is None:
            raise MediaCatalogNotFoundError()
        return entry

    async def set_lifecycle(
        self,
        catalog_id: str,
        *,
        lifecycle: MediaCatalogLifecycle,
        expected_version: int,
        operator_id: str,
        reason: str,
    ) -> MediaCatalogEntry:
        entries = list(await self.list_entries())
        entry = next((item for item in entries if item.catalog_id == catalog_id), None)
        if entry is None:
            raise MediaCatalogNotFoundError()
        if entry.lifecycle_version != expected_version:
            raise ConcurrentMediaCatalogWriteError()
        members = [
            candidate
            for candidate in entries
            if (
                candidate.catalog_id == entry.catalog_id
                or (
                    entry.sha256 is not None
                    and candidate.sha256 == entry.sha256
                    and candidate.media_kind is entry.media_kind
                )
            )
        ]
        changing = [member for member in members if member.lifecycle is not lifecycle]
        if not changing:
            return entry
        if lifecycle is MediaCatalogLifecycle.ACTIVE:
            for member in changing:
                await self._verify_content(member)
        now = datetime.now(UTC)
        archived = lifecycle is MediaCatalogLifecycle.ARCHIVED
        try:
            async with self._sessions() as session:
                async with session.begin():
                    for member in changing:
                        current_version = member.lifecycle_version
                        next_version = current_version + 1
                        existing = await session.get(
                            MediaCatalogLifecycleRow,
                            member.catalog_id,
                        )
                        if existing is None:
                            if current_version != 1:
                                raise ConcurrentMediaCatalogWriteError()
                            session.add(
                                MediaCatalogLifecycleRow(
                                    catalog_id=member.catalog_id,
                                    archived=archived,
                                    version=next_version,
                                    archived_at=now if archived else None,
                                    archived_by=operator_id if archived else None,
                                    archive_reason=reason if archived else None,
                                    updated_at=now,
                                )
                            )
                        else:
                            result = await session.execute(
                                update(MediaCatalogLifecycleRow)
                                .where(
                                    MediaCatalogLifecycleRow.catalog_id
                                    == member.catalog_id,
                                    MediaCatalogLifecycleRow.version == current_version,
                                )
                                .values(
                                    archived=archived,
                                    version=next_version,
                                    archived_at=now if archived else None,
                                    archived_by=operator_id if archived else None,
                                    archive_reason=reason if archived else None,
                                    updated_at=now,
                                )
                            )
                            if cast(CursorResult[Any], result).rowcount != 1:
                                raise ConcurrentMediaCatalogWriteError()
                        session.add(
                            MediaCatalogEventRow(
                                catalog_id=member.catalog_id,
                                action="archived" if archived else "restored",
                                operator_id=operator_id,
                                reason=reason,
                                resulting_version=next_version,
                                occurred_at=now,
                            )
                        )
        except IntegrityError as exc:
            raise ConcurrentMediaCatalogWriteError() from exc
        return await self.get_entry(catalog_id)

    async def is_archived(
        self,
        source_kind: MediaCatalogSourceKind,
        source_asset_id: UUID,
    ) -> bool:
        catalog_id = make_catalog_id(source_kind, source_asset_id)
        async with self._sessions() as session:
            row = await session.get(MediaCatalogLifecycleRow, catalog_id)
        return row is not None and row.archived

    async def protected_asset_paths(self) -> Sequence[Path]:
        result: list[Path] = []
        async with self._sessions() as session:
            visual_keys = (await session.scalars(select(VisualAssetRow.storage_key))).all()
            discovery_keys = (
                await session.scalars(
                    select(VisualDiscoveryAssetRow.storage_key).where(
                        VisualDiscoveryAssetRow.storage_key.is_not(None)
                    )
                )
            ).all()
            source_payloads = (
                await session.scalars(select(SourceMediaArtifactRow.artifact_json))
            ).all()
        for kind, keys in (
            (MediaCatalogSourceKind.VISUAL_ASSET, visual_keys),
            (MediaCatalogSourceKind.VISUAL_DISCOVERY, discovery_keys),
        ):
            for key in keys:
                if key is not None:
                    path = self._safe_path(kind, key)
                    if path is not None:
                        result.append(path)
        for payload in source_payloads:
            artifact = StoredSourceMediaArtifact.model_validate_json(payload)
            path = self._safe_path(MediaCatalogSourceKind.SOURCE_MEDIA, artifact.storage_key)
            if path is not None:
                result.append(path)
        return result

    async def resolve_content(self, catalog_id: str) -> tuple[MediaCatalogEntry, Path]:
        entry = await self.get_entry(catalog_id)
        await self._verify_content(entry)
        storage_key = await self._storage_key(entry)
        path = self._safe_path(entry.source_kind, storage_key)
        if path is None:
            raise MediaCatalogConflictError("Media catalog path is invalid.")
        return entry, path

    async def _verify_content(self, entry: MediaCatalogEntry) -> None:
        if not entry.has_local_content:
            # Staged external candidates have no local bytes yet. Their
            # recoverability is the durable source record and provider URL;
            # byte integrity starts once approval downloads the asset.
            return
        storage_key = await self._storage_key(entry)
        path = self._safe_path(entry.source_kind, storage_key)
        if path is None or not path.is_file():
            raise MediaCatalogConflictError(
                "Archived media bytes are missing; restore is not safe."
            )
        expected_size = entry.size_bytes
        expected_sha256 = entry.sha256

        def inspect() -> tuple[int, str]:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
            return size, digest.hexdigest()

        size, sha256 = await asyncio.to_thread(inspect)
        if expected_size is not None and size != expected_size:
            raise MediaCatalogConflictError("Archived media size changed; restore is not safe.")
        if expected_sha256 is not None and sha256 != expected_sha256:
            raise MediaCatalogConflictError("Archived media hash changed; restore is not safe.")

    async def _storage_key(self, entry: MediaCatalogEntry) -> str:
        async with self._sessions() as session:
            if entry.source_kind is MediaCatalogSourceKind.VISUAL_ASSET:
                visual_row = await session.get(VisualAssetRow, str(entry.source_asset_id))
                if visual_row is not None:
                    return visual_row.storage_key
            elif entry.source_kind is MediaCatalogSourceKind.VISUAL_DISCOVERY:
                discovery_row = await session.get(
                    VisualDiscoveryAssetRow,
                    str(entry.source_asset_id),
                )
                if discovery_row is not None and discovery_row.storage_key is not None:
                    return discovery_row.storage_key
            else:
                source_row = await session.get(
                    SourceMediaArtifactRow,
                    str(entry.source_asset_id),
                )
                if source_row is not None:
                    return StoredSourceMediaArtifact.model_validate_json(
                        source_row.artifact_json
                    ).storage_key
        raise MediaCatalogConflictError("Media source record is no longer available.")

    def _safe_path(self, kind: MediaCatalogSourceKind, storage_key: str) -> Path | None:
        root = self._roots[kind]
        path = (root / storage_key).resolve(strict=False)
        return path if path.is_relative_to(root) else None

    @staticmethod
    def _lifecycle(row: MediaCatalogLifecycleRow | None) -> MediaCatalogLifecycle:
        return (
            MediaCatalogLifecycle.ARCHIVED
            if row is not None and row.archived
            else MediaCatalogLifecycle.ACTIVE
        )

    @staticmethod
    def _story_is_active(story: StoryRow | None) -> bool:
        return story is not None and story.status != "ARCHIVED"

    @staticmethod
    def _story_usage_state(
        story: StoryRow | None,
        *,
        script_revision: int | None,
        segment_id: UUID | None,
    ) -> MediaUsageState:
        if story is None or story.status == "ARCHIVED" or story.script_json is None:
            return MediaUsageState.FROZEN
        try:
            script = ScriptDocument.model_validate_json(story.script_json)
        except ValueError:
            return MediaUsageState.FROZEN
        current_segments = {segment.segment_id for segment in script.segments}
        if (
            script_revision == script.revision
            and (segment_id is None or segment_id in current_segments)
        ):
            return MediaUsageState.ACTIVE
        return MediaUsageState.FROZEN

    @classmethod
    def _story_usages_for_visual(
        cls,
        row: VisualAssetRow,
        story: StoryRow | None,
    ) -> list[MediaAssetUsage]:
        segment_id = UUID(row.segment_id) if row.segment_id else None
        return [
            MediaAssetUsage(
                purpose=(
                    MediaUsagePurpose.STORY_SEGMENT
                    if row.origin == VisualAssetOrigin.EDITOR_UPLOAD.value
                    else MediaUsagePurpose.STORY_EVIDENCE
                ),
                state=cls._story_usage_state(
                    story,
                    script_revision=row.script_revision,
                    segment_id=segment_id,
                ),
                story_id=UUID(row.story_id),
                segment_id=segment_id,
                script_revision=row.script_revision,
            )
        ]

    @staticmethod
    def _batch_usages(
        payloads: Sequence[str],
    ) -> dict[str, list[MediaAssetUsage]]:
        usages: dict[str, list[MediaAssetUsage]] = defaultdict(list)
        for payload in payloads:
            try:
                batch = VideoBatch.model_validate_json(payload)
            except ValueError:
                continue
            props = batch.remotion_props
            plan = props.episode_plan if props is not None else None
            if plan is None:
                if batch.media_reservations_frozen:
                    for source_asset in batch.reserved_source_videos:
                        usages[
                            make_catalog_id(
                                MediaCatalogSourceKind.SOURCE_MEDIA,
                                source_asset.asset_id,
                            )
                        ].append(
                            MediaAssetUsage(
                                purpose=MediaUsagePurpose.BATCH_SCENE,
                                state=MediaUsageState.FROZEN,
                                story_id=source_asset.story_id,
                                batch_id=batch.batch_id,
                                batch_version=batch.version,
                            )
                        )
                    for broll_asset in batch.reserved_broll_videos:
                        usages[
                            make_catalog_id(
                                MediaCatalogSourceKind.VISUAL_DISCOVERY,
                                broll_asset.asset_id,
                            )
                        ].append(
                            MediaAssetUsage(
                                purpose=MediaUsagePurpose.BATCH_SCENE,
                                state=MediaUsageState.FROZEN,
                                story_id=broll_asset.story_id,
                                segment_id=broll_asset.segment_id,
                                batch_id=batch.batch_id,
                                batch_version=batch.version,
                            )
                        )
                continue
            assert props is not None
            for scene in plan.scenes:
                refs: list[tuple[MediaCatalogSourceKind, UUID]] = []
                for asset_id in scene.visual_asset_ids:
                    # The frozen render contract intentionally erases whether
                    # a reviewed image came from editor storage or Commons.
                    # Index both namespaces; only the matching source row is
                    # exposed by the catalog.
                    refs.extend(
                        (
                            (MediaCatalogSourceKind.VISUAL_ASSET, asset_id),
                            (MediaCatalogSourceKind.VISUAL_DISCOVERY, asset_id),
                        )
                    )
                if scene.source_video_asset_id is not None:
                    refs.append(
                        (
                            MediaCatalogSourceKind.SOURCE_MEDIA,
                            scene.source_video_asset_id,
                        )
                    )
                if scene.broll_video_asset_id is not None:
                    refs.append(
                        (
                            MediaCatalogSourceKind.VISUAL_DISCOVERY,
                            scene.broll_video_asset_id,
                        )
                    )
                for source_kind, asset_id in refs:
                    usages[make_catalog_id(source_kind, asset_id)].append(
                        MediaAssetUsage(
                            purpose=MediaUsagePurpose.BATCH_SCENE,
                            state=MediaUsageState.FROZEN,
                            story_id=(
                                next(
                                    (
                                        item.story_id
                                        for item in batch.stories
                                        if item.story_id
                                        in {
                                            asset.story_id
                                            for asset in (
                                                props.visual_assets
                                                + props.source_videos
                                                + props.broll_videos
                                            )
                                            if asset.asset_id == asset_id
                                        }
                                    ),
                                    batch.stories[0].story_id,
                                )
                            ),
                            segment_id=scene.narration_segment_id,
                            batch_id=batch.batch_id,
                            scene_sequence=scene.sequence,
                            batch_version=batch.version,
                            render_input_sha256=batch.render_input_sha256,
                        )
                    )
        return usages
