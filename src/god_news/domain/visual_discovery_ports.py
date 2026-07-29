"""Ports for discoverable, rights-evidenced visual material."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.visual_discovery import (
    CommonsDiscoveryRequest,
    CommonsDiscoveryResult,
    PersistedVisualDiscoveryAsset,
)


class VisualDiscoveryService(Protocol):
    """Search a trusted visual catalogue without exposing provider payloads."""

    async def discover(self, request: CommonsDiscoveryRequest) -> CommonsDiscoveryResult: ...


class VisualDiscoveryRepository(Protocol):
    async def create(self, asset: PersistedVisualDiscoveryAsset) -> None: ...

    async def get(self, asset_id: UUID) -> PersistedVisualDiscoveryAsset: ...

    async def list_for_story(
        self, story_id: UUID, *, script_revision: int
    ) -> list[PersistedVisualDiscoveryAsset]: ...

    async def set_status(
        self,
        asset_id: UUID,
        *,
        status: str,
        review_note: str | None,
    ) -> PersistedVisualDiscoveryAsset: ...


class VisualDiscoveryStore(Protocol):
    async def write_download(
        self,
        *,
        asset_id: UUID,
        filename: str,
        response: object,
        expected_max_bytes: int,
    ) -> tuple[str, str, int, Path]: ...

    async def clone(
        self,
        *,
        source_storage_key: str,
        target_asset_id: UUID,
        filename: str,
    ) -> tuple[str, str, int, Path]: ...

    async def resolve(self, storage_key: str) -> Path: ...

    async def remove(self, storage_key: str) -> None: ...
