from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.application.video_batches import require_video_transition
from god_news.domain.video import VideoBatch, VideoBatchStatus
from god_news.infrastructure.database import Base
from god_news.video_errors import (
    VideoBatchConflictError,
    VideoBatchNotFoundError,
    VideoStoryUnavailableError,
)


class VideoBatchRow(Base):
    __tablename__ = "video_batches"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    batch_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoStoryClaimRow(Base):
    """One active reservation or durable used marker per story.

    Rejected batches delete their claims. Successful batches keep the row with
    ``used_at`` populated, which makes candidate exclusion durable and cheap.
    """

    __tablename__ = "video_story_claims"

    story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("stories.story_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("video_batches.batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_batch(row: VideoBatchRow) -> VideoBatch:
    batch = VideoBatch.model_validate_json(row.batch_json)
    return batch.model_copy(
        update={
            "version": row.version,
            "created_at": _aware(row.created_at),
            "updated_at": _aware(row.updated_at),
        }
    )


class SqlAlchemyVideoBatchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, batch: VideoBatch) -> VideoBatch:
        batch = VideoBatch.model_validate(batch.model_dump())
        row = VideoBatchRow(
            batch_id=str(batch.batch_id),
            status=batch.status.value,
            batch_json=batch.model_dump_json(),
            version=batch.version,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )
        claims = [
            VideoStoryClaimRow(
                story_id=str(story.story_id),
                batch_id=str(batch.batch_id),
                reserved_at=story.reserved_at,
                used_at=None,
            )
            for story in batch.stories
        ]
        try:
            async with self._sessions() as session:
                async with session.begin():
                    session.add(row)
                    session.add_all(claims)
        except IntegrityError as exc:
            unavailable = await self.unavailable_story_ids(
                [story.story_id for story in batch.stories]
            )
            if unavailable:
                raise VideoStoryUnavailableError(list(unavailable)) from exc
            raise VideoBatchConflictError("Video batch could not be created atomically.") from exc
        return batch

    async def get(self, batch_id: UUID) -> VideoBatch:
        async with self._sessions() as session:
            row = await session.get(VideoBatchRow, str(batch_id))
        if row is None:
            raise VideoBatchNotFoundError(batch_id)
        return _to_batch(row)

    async def list(
        self,
        *,
        status: VideoBatchStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[VideoBatch]:
        statement = (
            select(VideoBatchRow)
            .order_by(VideoBatchRow.created_at.desc(), VideoBatchRow.batch_id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(VideoBatchRow.status == status.value)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_batch(row) for row in rows]

    async def unavailable_story_ids(self, story_ids: Sequence[UUID]) -> frozenset[UUID]:
        if not story_ids:
            return frozenset()
        encoded = [str(story_id) for story_id in story_ids]
        claimed: list[str] = []
        async with self._sessions() as session:
            for start in range(0, len(encoded), 500):
                statement = select(VideoStoryClaimRow.story_id).where(
                    VideoStoryClaimRow.story_id.in_(encoded[start : start + 500])
                )
                claimed.extend((await session.scalars(statement)).all())
        return frozenset(UUID(story_id) for story_id in claimed)

    async def save(self, batch: VideoBatch, *, expected_version: int) -> VideoBatch:
        batch = VideoBatch.model_validate(batch.model_dump())
        next_version = expected_version + 1
        saved = VideoBatch.model_validate(
            batch.model_copy(update={"version": next_version}).model_dump()
        )
        async with self._sessions() as session:
            async with session.begin():
                previous = await session.get(VideoBatchRow, str(batch.batch_id))
                if previous is None:
                    raise VideoBatchNotFoundError(batch.batch_id)
                require_video_transition(VideoBatchStatus(previous.status), saved.status)
                result = await session.execute(
                    update(VideoBatchRow)
                    .where(
                        VideoBatchRow.batch_id == str(saved.batch_id),
                        VideoBatchRow.version == expected_version,
                    )
                    .values(
                        status=saved.status.value,
                        batch_json=saved.model_dump_json(),
                        version=saved.version,
                        updated_at=saved.updated_at,
                    )
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise VideoBatchConflictError(
                        "Video batch changed concurrently; reload it and retry."
                    )
                if saved.status in {VideoBatchStatus.REJECTED, VideoBatchStatus.CANCELLED}:
                    await session.execute(
                        delete(VideoStoryClaimRow).where(
                            VideoStoryClaimRow.batch_id == str(saved.batch_id)
                        )
                    )
                elif saved.status is VideoBatchStatus.RENDERED:
                    used_at = saved.stories[0].used_at
                    assert used_at is not None
                    claim_result = await session.execute(
                        update(VideoStoryClaimRow)
                        .where(VideoStoryClaimRow.batch_id == str(saved.batch_id))
                        .values(used_at=used_at)
                    )
                    if cast(CursorResult[Any], claim_result).rowcount != len(saved.stories):
                        raise VideoBatchConflictError(
                            "Video story claims changed during rendering."
                        )
        return saved

    async def delete(self, batch_id: UUID) -> None:
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(VideoBatchRow, str(batch_id))
                if row is None:
                    raise VideoBatchNotFoundError(batch_id)
                status = VideoBatchStatus(row.status)
                if status in {VideoBatchStatus.RENDERING, VideoBatchStatus.RENDERED}:
                    raise VideoBatchConflictError(
                        "A rendering or rendered batch cannot be deleted because its claims are "
                        "audit evidence."
                    )
                await session.execute(
                    delete(VideoStoryClaimRow).where(VideoStoryClaimRow.batch_id == str(batch_id))
                )
                await session.execute(
                    delete(VideoBatchRow).where(VideoBatchRow.batch_id == str(batch_id))
                )

    async def protected_asset_paths(self) -> Sequence[Path]:
        active = (
            VideoBatchStatus.PENDING_TIMELINE_REVIEW.value,
            VideoBatchStatus.READY_TO_RENDER.value,
            VideoBatchStatus.RENDERING.value,
            VideoBatchStatus.FAILED.value,
        )
        async with self._sessions() as session:
            payloads = (
                await session.scalars(
                    select(VideoBatchRow.batch_json).where(VideoBatchRow.status.in_(active))
                )
            ).all()
        result: list[Path] = []
        for payload in payloads:
            batch = VideoBatch.model_validate_json(payload)
            result.extend(Path(asset.local_path) for asset in batch.input_assets)
        return result

    async def healthcheck(self) -> None:
        async with self._sessions() as session:
            await session.execute(select(1))
