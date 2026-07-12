from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.operations.errors import RoleProfileConflictError
from god_news.operations.models import (
    RoleProfile,
    RoleProfileCreate,
    RoleProfileReplace,
    utc_now,
)
from god_news.operations.ports import RoleProfileRepository


class RoleProfileService:
    """Application service for versioned narrator/host profiles."""

    def __init__(self, repository: RoleProfileRepository) -> None:
        self._repository = repository

    async def create(self, request: RoleProfileCreate) -> RoleProfile:
        now = utc_now()
        profile = RoleProfile(
            **request.model_dump(),
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create(profile)

    async def get(self, profile_id: UUID) -> RoleProfile:
        return await self._repository.get(profile_id)

    async def list(self, *, enabled: bool | None = None) -> Sequence[RoleProfile]:
        return await self._repository.list(enabled=enabled)

    async def replace(self, profile_id: UUID, request: RoleProfileReplace) -> RoleProfile:
        current = await self._repository.get(profile_id)
        if current.version != request.expected_version:
            raise RoleProfileConflictError()
        values = request.model_dump(exclude={"expected_version"})
        replacement = RoleProfile(
            profile_id=current.profile_id,
            **values,
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        return await self._repository.replace(
            replacement,
            expected_version=request.expected_version,
        )

    async def delete(self, profile_id: UUID, *, expected_version: int) -> RoleProfile:
        """Soft-disable a role while retaining its historical configuration.

        The HTTP operation keeps its DELETE spelling, but profiles may be
        referenced by already-produced scripts and manifests.  We therefore
        retain the row and perform the state change through the same atomic
        versioned replacement path used by edits.
        """

        current = await self._repository.get(profile_id)
        if current.version != expected_version:
            raise RoleProfileConflictError()
        if not current.enabled:
            return current
        disabled = current.model_copy(
            update={
                "enabled": False,
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        return await self._repository.replace(disabled, expected_version=expected_version)
