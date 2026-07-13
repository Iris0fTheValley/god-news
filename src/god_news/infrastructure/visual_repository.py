from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.visual_assets import (
    ImageContentType,
    StoredVisualAsset,
    VisualAssetOrigin,
)
from god_news.errors import ConcurrentWriteError, StoryNotFoundError, VisualAssetNotFoundError
from god_news.infrastructure.database import Base
from god_news.infrastructure.repositories import StoryRow


class VisualAssetRow(Base):
    """One active editor image per story/segment/script-revision binding.

    Old script revisions deliberately retain their rows until the media
    lifecycle expires. This preserves an audit trail without allowing a stale
    image to silently appear on a revised script because reads are revision
    scoped.
    """

    __tablename__ = "visual_assets"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("stories.story_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    script_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "story_id",
            "segment_id",
            "script_revision",
            name="uq_visual_assets_story_segment_revision",
        ),
        Index("ix_visual_assets_story_origin_created", "story_id", "origin", "created_at"),
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_asset(row: VisualAssetRow) -> StoredVisualAsset:
    return StoredVisualAsset(
        asset_id=UUID(row.asset_id),
        story_id=UUID(row.story_id),
        segment_id=UUID(row.segment_id) if row.segment_id is not None else None,
        script_revision=row.script_revision,
        origin=VisualAssetOrigin(row.origin),
        content_type=ImageContentType(row.content_type),
        filename=row.filename,
        storage_key=row.storage_key,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        created_at=_aware(row.created_at),
    )


def _to_row(asset: StoredVisualAsset) -> VisualAssetRow:
    return VisualAssetRow(
        asset_id=str(asset.asset_id),
        story_id=str(asset.story_id),
        segment_id=str(asset.segment_id) if asset.segment_id is not None else None,
        script_revision=asset.script_revision,
        origin=asset.origin.value,
        content_type=asset.content_type.value,
        filename=asset.filename,
        storage_key=asset.storage_key,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        created_at=asset.created_at,
    )


class SqlAlchemyVisualAssetRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        storage_root: Path,
    ) -> None:
        self._sessions = sessions
        self._storage_root = storage_root.expanduser().resolve(strict=False)

    async def list_for_script(
        self,
        story_id: UUID,
        *,
        script_revision: int,
    ) -> Sequence[StoredVisualAsset]:
        statement = (
            select(VisualAssetRow)
            .where(
                VisualAssetRow.story_id == str(story_id),
                (
                    (VisualAssetRow.origin == VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT.value)
                    | (
                        (VisualAssetRow.origin == VisualAssetOrigin.EDITOR_UPLOAD.value)
                        & (VisualAssetRow.script_revision == script_revision)
                    )
                ),
            )
            .order_by(VisualAssetRow.created_at.asc(), VisualAssetRow.asset_id.asc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_asset(row) for row in rows]

    async def get(self, story_id: UUID, asset_id: UUID) -> StoredVisualAsset:
        async with self._sessions() as session:
            row = await session.get(VisualAssetRow, str(asset_id))
        if row is None or row.story_id != str(story_id):
            raise VisualAssetNotFoundError(story_id)
        return _to_asset(row)

    async def replace_segment_upload(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        if asset.origin is not VisualAssetOrigin.EDITOR_UPLOAD:
            raise ValueError("segment replacement requires an editor-upload asset")
        if asset.segment_id is None or asset.script_revision is None:
            raise ValueError("segment replacement requires a script binding")
        async with self._sessions() as session:
            async with session.begin():
                next_story_version = await self._advance_story_version(
                    session,
                    story_id=asset.story_id,
                    expected_story_version=expected_story_version,
                )
                existing = await session.scalar(
                    select(VisualAssetRow).where(
                        VisualAssetRow.story_id == str(asset.story_id),
                        VisualAssetRow.segment_id == str(asset.segment_id),
                        VisualAssetRow.script_revision == asset.script_revision,
                    )
                )
                replaced = _to_asset(existing) if existing is not None else None
                if existing is not None:
                    await session.delete(existing)
                    await session.flush()
                session.add(_to_row(asset))
        return replaced, next_story_version

    async def delete_segment_upload(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        script_revision: int,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        async with self._sessions() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(VisualAssetRow).where(
                        VisualAssetRow.story_id == str(story_id),
                        VisualAssetRow.segment_id == str(segment_id),
                        VisualAssetRow.script_revision == script_revision,
                        VisualAssetRow.origin == VisualAssetOrigin.EDITOR_UPLOAD.value,
                    )
                )
                if existing is None:
                    # A no-op delete must not invalidate an otherwise-current
                    # editor with a spurious story version bump.
                    return None, expected_story_version
                next_story_version = await self._advance_story_version(
                    session,
                    story_id=story_id,
                    expected_story_version=expected_story_version,
                )
                removed = _to_asset(existing)
                await session.delete(existing)
        return removed, next_story_version

    async def replace_source_screenshot(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        if asset.origin is not VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT:
            raise ValueError("source screenshot replacement requires a screenshot asset")
        async with self._sessions() as session:
            async with session.begin():
                next_story_version = await self._advance_story_version(
                    session,
                    story_id=asset.story_id,
                    expected_story_version=expected_story_version,
                )
                existing_rows = (
                    await session.scalars(
                        select(VisualAssetRow).where(
                            VisualAssetRow.story_id == str(asset.story_id),
                            VisualAssetRow.origin == VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT.value,
                        )
                    )
                ).all()
                replaced = _to_asset(existing_rows[-1]) if existing_rows else None
                for existing in existing_rows:
                    await session.delete(existing)
                if existing_rows:
                    await session.flush()
                session.add(_to_row(asset))
        return replaced, next_story_version

    async def protected_asset_paths(self) -> Sequence[Path]:
        """Keep assets for non-archived stories out of generic media retention.

        Archived stories deliberately lose this protection so the existing
        retention job can reclaim both current and historical script visuals.
        The returned paths remain rooted locally; the cleanup handler repeats
        its own path checks before it mutates any file.
        """

        statement = (
            select(VisualAssetRow.storage_key)
            .join(StoryRow, StoryRow.story_id == VisualAssetRow.story_id)
            .where(StoryRow.status != "ARCHIVED")
        )
        async with self._sessions() as session:
            storage_keys = (await session.scalars(statement)).all()
        paths: list[Path] = []
        for key in storage_keys:
            try:
                path = self._storage_path(key)
            except ValueError:
                continue
            paths.append(path)
        return paths

    def _storage_path(self, storage_key: str) -> Path:
        candidate = self._storage_root / storage_key
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._storage_root):
            raise ValueError("stored visual key escaped its configured root")
        return resolved

    @staticmethod
    async def _advance_story_version(
        session: AsyncSession,
        *,
        story_id: UUID,
        expected_story_version: int,
    ) -> int:
        result = await session.execute(
            update(StoryRow)
            .where(
                StoryRow.story_id == str(story_id),
                StoryRow.version == expected_story_version,
            )
            .values(
                version=StoryRow.version + 1,
                updated_at=datetime.now(UTC),
            )
        )
        if cast(CursorResult[Any], result).rowcount == 1:
            return expected_story_version + 1
        story = await session.get(StoryRow, str(story_id))
        if story is None:
            raise StoryNotFoundError(story_id)
        raise ConcurrentWriteError(story_id)
