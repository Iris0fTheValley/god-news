from __future__ import annotations

import asyncio
import builtins
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
        source_filtered = [
            item
            for item in await self._repository.list_entries()
            if (source_kind is None or item.source_kind is source_kind)
            and (media_kind is None or item.media_kind is media_kind)
            and (lifecycle is None or item.lifecycle is lifecycle)
            and (
                publish_eligible is None
                or item.publish_eligible is publish_eligible
            )
        ]
        items = [
            item
            for item in self._group_by_content(source_filtered)
            if (
                story_id is None
                or story_id in item.story_references
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

    @staticmethod
    def _group_by_content(
        entries: builtins.list[MediaCatalogEntry],
    ) -> builtins.list[MediaCatalogEntry]:
        groups: dict[str, builtins.list[MediaCatalogEntry]] = {}
        for entry in entries:
            key = (
                f"{entry.media_kind.value}:{entry.sha256}"
                if entry.sha256 is not None
                else entry.catalog_id
            )
            groups.setdefault(key, []).append(entry)

        grouped: builtins.list[MediaCatalogEntry] = []
        for members in groups.values():
            representative = min(
                members,
                key=lambda item: (
                    not item.has_local_content,
                    item.lifecycle is MediaCatalogLifecycle.ARCHIVED,
                    item.catalog_id,
                ),
            )
            usages = {
                (
                    usage.purpose,
                    usage.state,
                    usage.story_id,
                    usage.segment_id,
                    usage.script_revision,
                    usage.batch_id,
                    usage.scene_sequence,
                    usage.batch_version,
                    usage.render_input_sha256,
                ): usage
                for member in members
                for usage in member.usages
            }
            story_references = sorted(
                {
                    member.story_id
                    for member in members
                }
                | {usage.story_id for usage in usages.values()},
                key=str,
            )
            grouped.append(
                representative.model_copy(
                    update={
                        "member_catalog_ids": sorted(
                            (member.catalog_id for member in members),
                        ),
                        "story_references": story_references,
                        "content_occurrence_count": len(members),
                        "usages": list(usages.values())[:100],
                        "selectable": any(member.selectable for member in members),
                        "publish_eligible": any(
                            member.publish_eligible for member in members
                        ),
                        "reusable": any(member.reusable for member in members),
                    }
                )
            )
        return sorted(grouped, key=lambda item: (item.filename.casefold(), item.catalog_id))

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
