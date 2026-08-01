from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.domain.media_catalog import MediaCatalogSourceKind
from god_news.domain.media_catalog_ports import MediaCatalogRepository
from god_news.domain.ports import StoryRepository
from god_news.domain.video import BrollVideoRenderAsset
from god_news.domain.visual_discovery import CommonsMediaKind, VisualDiscoveryStatus
from god_news.domain.visual_discovery_ports import (
    VisualDiscoveryRepository,
    VisualDiscoveryStore,
)


class ApprovedVisualDiscoveryBrollLibrary:
    """Adapt current, approved Commons videos into immutable render assets."""

    def __init__(
        self,
        *,
        stories: StoryRepository,
        repository: VisualDiscoveryRepository,
        store: VisualDiscoveryStore,
        media_catalog: MediaCatalogRepository | None = None,
    ) -> None:
        self._stories = stories
        self._repository = repository
        self._store = store
        self._media_catalog = media_catalog

    async def approved_for_stories(
        self,
        story_ids: Sequence[UUID],
    ) -> Sequence[BrollVideoRenderAsset]:
        result: list[BrollVideoRenderAsset] = []
        for story_id in story_ids:
            story = await self._stories.get(story_id)
            if story.script is None:
                continue
            assets = await self._repository.list_for_story(
                story_id,
                script_revision=story.script.revision,
            )
            for asset in assets:
                candidate = asset.candidate
                if (
                    asset.status is not VisualDiscoveryStatus.APPROVED
                    or candidate.kind is not CommonsMediaKind.VIDEO
                    or not candidate.publish_eligible
                    or asset.storage_key is None
                    or asset.sha256 is None
                    or asset.downloaded_size_bytes is None
                    or asset.probed_duration_ms is None
                    or (
                        self._media_catalog is not None
                        and await self._media_catalog.is_archived(
                            MediaCatalogSourceKind.VISUAL_DISCOVERY,
                            asset.asset_id,
                        )
                    )
                ):
                    continue
                path = await self._store.resolve(asset.storage_key)
                result.append(
                    BrollVideoRenderAsset(
                        asset_id=asset.asset_id,
                        story_id=asset.story_id,
                        segment_id=asset.segment_id,
                        local_path=str(path),
                        sha256=asset.sha256,
                        size_bytes=asset.downloaded_size_bytes,
                        duration_ms=asset.probed_duration_ms,
                        width=candidate.width,
                        height=candidate.height,
                        out_ms=asset.probed_duration_ms,
                        source_label=candidate.file_title.removeprefix("File:"),
                        source_url=str(candidate.canonical_page_url),
                        license=candidate.rights.license.value,
                        attribution=candidate.attribution.attribution_text,
                    )
                )
        return result
