from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from god_news.domain.media_catalog import (
    ChangeMediaLifecycleRequest,
    MediaCatalogEntry,
    MediaCatalogKind,
    MediaCatalogLifecycle,
    MediaCatalogPage,
    MediaCatalogSourceKind,
)
from god_news.domain.media_catalog_ports import MediaCatalogRepository


class MediaCatalogService:
    """Global, rights-aware media inventory without owning source bytes."""

    def __init__(
        self,
        *,
        repository: MediaCatalogRepository,
        asset_lifecycle_lock: asyncio.Lock | None = None,
    ) -> None:
        self._repository = repository
        self._asset_lifecycle_lock = asset_lifecycle_lock or asyncio.Lock()

    async def list(
        self,
        *,
        search: str | None,
        source_kind: MediaCatalogSourceKind | None,
        media_kind: MediaCatalogKind | None,
        lifecycle: MediaCatalogLifecycle | None,
        story_id: UUID | None,
        publish_eligible: bool | None,
        limit: int,
        offset: int,
    ) -> MediaCatalogPage:
        normalized = (search or "").strip().casefold()
        items = [
            item
            for item in await self._repository.list_entries()
            if (source_kind is None or item.source_kind is source_kind)
            and (media_kind is None or item.media_kind is media_kind)
            and (lifecycle is None or item.lifecycle is lifecycle)
            and (story_id is None or item.story_id == story_id)
            and (
                publish_eligible is None
                or item.publish_eligible is publish_eligible
            )
            and (
                not normalized
                or any(
                    normalized in value.casefold()
                    for value in (
                        item.filename,
                        item.attribution or "",
                        item.license_label or "",
                        item.source_url or "",
                        item.editorial_state,
                    )
                )
            )
        ]
        return MediaCatalogPage(
            items=items[offset : offset + limit],
            total=len(items),
            limit=limit,
            offset=offset,
        )

    async def get(self, catalog_id: str) -> MediaCatalogEntry:
        return await self._repository.get_entry(catalog_id)

    async def archive(
        self,
        catalog_id: str,
        request: ChangeMediaLifecycleRequest,
    ) -> MediaCatalogEntry:
        async with self._asset_lifecycle_lock:
            return await self._repository.set_lifecycle(
                catalog_id,
                lifecycle=MediaCatalogLifecycle.ARCHIVED,
                expected_version=request.expected_version,
                operator_id=request.operator_id,
                reason=request.reason,
            )

    async def restore(
        self,
        catalog_id: str,
        request: ChangeMediaLifecycleRequest,
    ) -> MediaCatalogEntry:
        async with self._asset_lifecycle_lock:
            return await self._repository.set_lifecycle(
                catalog_id,
                lifecycle=MediaCatalogLifecycle.ACTIVE,
                expected_version=request.expected_version,
                operator_id=request.operator_id,
                reason=request.reason,
            )

    async def media_path(self, catalog_id: str) -> tuple[str, str, Path]:
        entry, path = await self._repository.resolve_content(catalog_id)
        return entry.mime_type, entry.filename, path
