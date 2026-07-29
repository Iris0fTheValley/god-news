from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.visual_discovery import PersistedVisualDiscoveryAsset, VisualDiscoveryStatus
from god_news.errors import StoryNotFoundError
from god_news.infrastructure.database import Base


class VisualDiscoveryAssetRow(Base):
    __tablename__ = "visual_discovery_assets"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stories.story_id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    script_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    candidate_json: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    downloaded_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probed_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_model(row: VisualDiscoveryAssetRow) -> PersistedVisualDiscoveryAsset:
    return PersistedVisualDiscoveryAsset.model_validate(
        {
            "asset_id": row.asset_id,
            "story_id": row.story_id,
            "segment_id": row.segment_id,
            "script_revision": row.script_revision,
            "status": row.status,
            "candidate": json.loads(row.candidate_json),
            "storage_key": row.storage_key,
            "sha256": row.sha256,
            "downloaded_size_bytes": row.downloaded_size_bytes,
            "probed_duration_ms": row.probed_duration_ms,
            "review_note": row.review_note,
            "reviewed_at": _aware(row.reviewed_at),
            "created_at": _aware(row.created_at),
        }
    )


class SqlAlchemyVisualDiscoveryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, storage_root: Path) -> None:
        self._sessions = sessions
        self._storage_root = storage_root.expanduser().resolve(strict=False)

    async def create(self, asset: PersistedVisualDiscoveryAsset) -> None:
        row = VisualDiscoveryAssetRow(
            asset_id=str(asset.asset_id),
            story_id=str(asset.story_id),
            segment_id=str(asset.segment_id),
            script_revision=asset.script_revision,
            status=asset.status.value,
            candidate_json=json.dumps(
                asset.candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
            ),
            storage_key=asset.storage_key,
            sha256=asset.sha256,
            downloaded_size_bytes=asset.downloaded_size_bytes,
            probed_duration_ms=asset.probed_duration_ms,
            review_note=asset.review_note,
            reviewed_at=asset.reviewed_at,
            created_at=asset.created_at,
        )
        async with self._sessions() as session:
            async with session.begin():
                session.add(row)

    async def get(self, asset_id: UUID) -> PersistedVisualDiscoveryAsset:
        async with self._sessions() as session:
            row = await session.get(VisualDiscoveryAssetRow, str(asset_id))
        if row is None:
            raise StoryNotFoundError(asset_id)
        return _to_model(row)

    async def list_for_story(
        self, story_id: UUID, *, script_revision: int
    ) -> list[PersistedVisualDiscoveryAsset]:
        statement = (
            select(VisualDiscoveryAssetRow)
            .where(
                VisualDiscoveryAssetRow.story_id == str(story_id),
                VisualDiscoveryAssetRow.script_revision == script_revision,
            )
            .order_by(VisualDiscoveryAssetRow.created_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_model(row) for row in rows]

    async def set_status(
        self, asset_id: UUID, *, status: str, review_note: str | None
    ) -> PersistedVisualDiscoveryAsset:
        async with self._sessions() as session:
            async with session.begin():
                result = await session.execute(
                    update(VisualDiscoveryAssetRow)
                    .where(VisualDiscoveryAssetRow.asset_id == str(asset_id))
                    .values(status=status, review_note=review_note, reviewed_at=datetime.now(UTC))
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise StoryNotFoundError(asset_id)
                row = await session.get(VisualDiscoveryAssetRow, str(asset_id))
                assert row is not None
                return _to_model(row)

    async def protected_asset_paths(self) -> list[Path]:
        statement = select(VisualDiscoveryAssetRow.storage_key).where(
            VisualDiscoveryAssetRow.status == VisualDiscoveryStatus.APPROVED.value,
            VisualDiscoveryAssetRow.storage_key.is_not(None),
        )
        async with self._sessions() as session:
            keys = (await session.scalars(statement)).all()
        paths: list[Path] = []
        for key in keys:
            if key is None:
                continue
            path = (self._storage_root / key).resolve(strict=False)
            if path.is_relative_to(self._storage_root):
                paths.append(path)
        return paths
