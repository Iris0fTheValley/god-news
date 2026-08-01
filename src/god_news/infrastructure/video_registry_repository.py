from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.video_registry import VideoCapabilityPolicy
from god_news.errors import ConcurrentVideoCapabilityWriteError
from god_news.infrastructure.database import Base


class VideoCapabilityPolicyRow(Base):
    __tablename__ = "video_capability_policies"

    capability_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    enabled_for_new_batches: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoCapabilityPolicyEventRow(Base):
    __tablename__ = "video_capability_policy_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    enabled_for_new_batches: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resulting_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_policy(row: VideoCapabilityPolicyRow) -> VideoCapabilityPolicy:
    return VideoCapabilityPolicy(
        key=row.capability_key,
        enabled_for_new_batches=row.enabled_for_new_batches,
        version=row.version,
        reason=row.reason,
        updated_by=row.updated_by,
        updated_at=_aware(row.updated_at),
    )


class SqlAlchemyVideoCapabilityPolicyRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> VideoCapabilityPolicy:
        async with self._sessions() as session:
            row = await session.get(VideoCapabilityPolicyRow, key)
        return _to_policy(row) if row is not None else VideoCapabilityPolicy(key=key)

    async def list(self) -> dict[str, VideoCapabilityPolicy]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(VideoCapabilityPolicyRow))).all()
        return {row.capability_key: _to_policy(row) for row in rows}

    async def set(
        self,
        *,
        key: str,
        enabled_for_new_batches: bool,
        expected_version: int,
        reason: str,
        operator_id: str,
    ) -> VideoCapabilityPolicy:
        current = await self.get(key)
        if current.version != expected_version:
            raise ConcurrentVideoCapabilityWriteError()
        if current.enabled_for_new_batches is enabled_for_new_batches:
            return current
        now = datetime.now(UTC)
        next_version = expected_version + 1
        try:
            async with self._sessions() as session:
                async with session.begin():
                    row = await session.get(VideoCapabilityPolicyRow, key)
                    if row is None:
                        if expected_version != 1:
                            raise ConcurrentVideoCapabilityWriteError()
                        session.add(
                            VideoCapabilityPolicyRow(
                                capability_key=key,
                                enabled_for_new_batches=enabled_for_new_batches,
                                version=next_version,
                                reason=reason,
                                updated_by=operator_id,
                                updated_at=now,
                            )
                        )
                    else:
                        result = await session.execute(
                            update(VideoCapabilityPolicyRow)
                            .where(
                                VideoCapabilityPolicyRow.capability_key == key,
                                VideoCapabilityPolicyRow.version == expected_version,
                            )
                            .values(
                                enabled_for_new_batches=enabled_for_new_batches,
                                version=next_version,
                                reason=reason,
                                updated_by=operator_id,
                                updated_at=now,
                            )
                        )
                        if cast(CursorResult[Any], result).rowcount != 1:
                            raise ConcurrentVideoCapabilityWriteError()
                    session.add(
                        VideoCapabilityPolicyEventRow(
                            capability_key=key,
                            enabled_for_new_batches=enabled_for_new_batches,
                            resulting_version=next_version,
                            reason=reason,
                            updated_by=operator_id,
                            occurred_at=now,
                        )
                    )
        except IntegrityError as exc:
            raise ConcurrentVideoCapabilityWriteError() from exc
        return await self.get(key)
