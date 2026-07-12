from __future__ import annotations

import asyncio
import copy
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.infrastructure.database import Base
from god_news.operations.errors import RoleProfileConflictError, RoleProfileNotFoundError
from god_news.operations.models import RoleKind, RoleProfile, RoleVisualAssets


class RoleProfileRow(Base):
    __tablename__ = "role_profiles"

    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    speaker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    default_emotion: Mapped[str] = mapped_column(String(100), nullable=False)
    default_speed: Mapped[float] = mapped_column(Float, nullable=False)
    default_pitch: Mapped[float] = mapped_column(Float, nullable=False)
    gpt_weights_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    sovits_weights_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    visual_assets_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_values(profile: RoleProfile) -> dict[str, object]:
    return {
        "slug": profile.slug,
        "display_name": profile.display_name,
        "kind": profile.kind.value,
        "speaker_id": profile.speaker_id,
        "default_emotion": profile.default_emotion,
        "default_speed": profile.default_speed,
        "default_pitch": profile.default_pitch,
        "gpt_weights_path": profile.gpt_weights_path,
        "sovits_weights_path": profile.sovits_weights_path,
        "visual_assets_json": profile.visual_assets.model_dump_json(),
        "enabled": profile.enabled,
        "version": profile.version,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _to_profile(row: RoleProfileRow) -> RoleProfile:
    return RoleProfile(
        profile_id=UUID(row.profile_id),
        slug=row.slug,
        display_name=row.display_name,
        kind=RoleKind(row.kind),
        speaker_id=row.speaker_id,
        default_emotion=row.default_emotion,
        default_speed=row.default_speed,
        default_pitch=row.default_pitch,
        gpt_weights_path=row.gpt_weights_path,
        sovits_weights_path=row.sovits_weights_path,
        visual_assets=RoleVisualAssets.model_validate_json(row.visual_assets_json),
        enabled=row.enabled,
        version=row.version,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


class SqlAlchemyRoleProfileRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, profile: RoleProfile) -> RoleProfile:
        row = RoleProfileRow(profile_id=str(profile.profile_id), **_row_values(profile))
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            raise RoleProfileConflictError("A role profile with that slug already exists.") from exc
        return profile

    async def get(self, profile_id: UUID) -> RoleProfile:
        async with self._sessions() as session:
            row = await session.get(RoleProfileRow, str(profile_id))
        if row is None:
            raise RoleProfileNotFoundError(profile_id)
        return _to_profile(row)

    async def list(self, *, enabled: bool | None = None) -> Sequence[RoleProfile]:
        statement = select(RoleProfileRow)
        if enabled is not None:
            statement = statement.where(RoleProfileRow.enabled.is_(enabled))
        statement = statement.order_by(RoleProfileRow.slug)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_profile(row) for row in rows]

    async def replace(self, profile: RoleProfile, *, expected_version: int) -> RoleProfile:
        values = _row_values(profile)
        values.pop("created_at")
        try:
            async with self._sessions() as session, session.begin():
                result = await session.execute(
                    update(RoleProfileRow)
                    .where(
                        RoleProfileRow.profile_id == str(profile.profile_id),
                        RoleProfileRow.version == expected_version,
                    )
                    .values(**values)
                )
                rowcount = result.rowcount if isinstance(result, CursorResult) else 0
        except IntegrityError as exc:
            raise RoleProfileConflictError("A role profile with that slug already exists.") from exc
        if rowcount != 1:
            await self._raise_missing_or_conflict(profile.profile_id)
        return profile

    async def _raise_missing_or_conflict(self, profile_id: UUID) -> None:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(RoleProfileRow.profile_id)
                .where(RoleProfileRow.profile_id == str(profile_id))
                .limit(1)
            )
        if exists is None:
            raise RoleProfileNotFoundError(profile_id)
        raise RoleProfileConflictError()


class InMemoryRoleProfileRepository:
    """Deterministic adapter for API tests and the offline demo."""

    def __init__(self) -> None:
        self._profiles: dict[UUID, RoleProfile] = {}
        self._lock = asyncio.Lock()

    async def create(self, profile: RoleProfile) -> RoleProfile:
        async with self._lock:
            if any(existing.slug == profile.slug for existing in self._profiles.values()):
                raise RoleProfileConflictError("A role profile with that slug already exists.")
            self._profiles[profile.profile_id] = copy.deepcopy(profile)
        return copy.deepcopy(profile)

    async def get(self, profile_id: UUID) -> RoleProfile:
        async with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                raise RoleProfileNotFoundError(profile_id)
            return copy.deepcopy(profile)

    async def list(self, *, enabled: bool | None = None) -> Sequence[RoleProfile]:
        async with self._lock:
            profiles = [
                copy.deepcopy(profile)
                for profile in self._profiles.values()
                if enabled is None or profile.enabled is enabled
            ]
        return sorted(profiles, key=lambda profile: profile.slug)

    async def replace(self, profile: RoleProfile, *, expected_version: int) -> RoleProfile:
        async with self._lock:
            current = self._profiles.get(profile.profile_id)
            if current is None:
                raise RoleProfileNotFoundError(profile.profile_id)
            if current.version != expected_version:
                raise RoleProfileConflictError()
            if any(
                item.profile_id != profile.profile_id and item.slug == profile.slug
                for item in self._profiles.values()
            ):
                raise RoleProfileConflictError("A role profile with that slug already exists.")
            self._profiles[profile.profile_id] = copy.deepcopy(profile)
        return copy.deepcopy(profile)
