from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.operations.models import (
    OperationCommand,
    OperationKind,
    OperationResult,
    RoleProfile,
)


class RoleProfileRepository(Protocol):
    async def create(self, profile: RoleProfile) -> RoleProfile: ...

    async def get(self, profile_id: UUID) -> RoleProfile: ...

    async def list(self, *, enabled: bool | None = None) -> Sequence[RoleProfile]: ...

    async def get_enabled_by_speaker_id(self, speaker_id: str) -> RoleProfile | None: ...

    async def replace(self, profile: RoleProfile, *, expected_version: int) -> RoleProfile: ...


class LiveScriptRoleUsageGuard(Protocol):
    """Answers whether a persisted script can still select a role by speaker id.

    The role service owns the mutation policy; a story-side adapter owns the
    status query. Keeping this port one-way prevents role management from
    importing the story repository or its persistence implementation.
    """

    async def has_live_script_reference(self, speaker_id: str) -> bool: ...


class OperationHandler(Protocol):
    @property
    def kind(self) -> OperationKind: ...

    async def execute(self, command: OperationCommand) -> OperationResult: ...


class RetentionAssetProtector(Protocol):
    """Provides assets claimed by active video batches and therefore not disposable."""

    async def protected_asset_paths(self) -> Sequence[Path]: ...
