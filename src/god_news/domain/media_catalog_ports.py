from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.media_catalog import (
    MediaCatalogEntry,
    MediaCatalogLifecycle,
    MediaCatalogSourceKind,
)


class MediaCatalogRepository(Protocol):
    async def list_entries(self) -> Sequence[MediaCatalogEntry]: ...

    async def get_entry(self, catalog_id: str) -> MediaCatalogEntry: ...

    async def set_lifecycle(
        self,
        catalog_id: str,
        *,
        lifecycle: MediaCatalogLifecycle,
        expected_version: int,
        operator_id: str,
        reason: str,
    ) -> MediaCatalogEntry: ...

    async def is_archived(
        self,
        source_kind: MediaCatalogSourceKind,
        source_asset_id: UUID,
    ) -> bool: ...

    async def resolve_content(self, catalog_id: str) -> tuple[MediaCatalogEntry, Path]: ...

    async def protected_asset_paths(self) -> Sequence[Path]: ...


class MediaCatalogArchiveReader(Protocol):
    async def is_archived(
        self,
        source_kind: MediaCatalogSourceKind,
        source_asset_id: UUID,
    ) -> bool: ...
