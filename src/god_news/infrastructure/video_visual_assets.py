from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit
from uuid import UUID

from god_news.domain.media_catalog import MediaCatalogSourceKind
from god_news.domain.media_catalog_ports import MediaCatalogRepository
from god_news.domain.models import Story
from god_news.domain.video import VisualAssetType, VisualRenderAsset
from god_news.domain.visual_assets import (
    StoredVisualAsset,
    VisualAssetOrigin,
)
from god_news.domain.visual_discovery import CommonsMediaKind, VisualDiscoveryStatus
from god_news.domain.visual_discovery_ports import (
    VisualDiscoveryRepository,
    VisualDiscoveryStore,
)
from god_news.domain.visual_ports import VisualAssetRepository, VisualAssetStore
from god_news.infrastructure.visual_asset_store import inspect_raster_dimensions


class ApprovedVisualAssetLibrary:
    """Adapt current story visuals into immutable renderer-facing evidence."""

    def __init__(
        self,
        *,
        repository: VisualAssetRepository,
        store: VisualAssetStore,
        discovery_repository: VisualDiscoveryRepository | None = None,
        discovery_store: VisualDiscoveryStore | None = None,
        media_catalog: MediaCatalogRepository | None = None,
    ) -> None:
        self._repository = repository
        self._store = store
        self._discovery_repository = discovery_repository
        self._discovery_store = discovery_store
        self._media_catalog = media_catalog

    async def approved_for_stories(
        self,
        stories: Sequence[Story],
    ) -> dict[UUID, Sequence[VisualRenderAsset]]:
        result: dict[UUID, Sequence[VisualRenderAsset]] = {}
        for story in stories:
            if story.script is None:
                result[story.story_id] = ()
                continue
            assets = await self._repository.list_for_script(
                story.story_id,
                script_revision=story.script.revision,
            )
            rendered = [
                await self._to_render_asset(story, asset)
                for asset in assets
                if self._media_catalog is None
                or not await self._media_catalog.is_archived(
                    MediaCatalogSourceKind.VISUAL_ASSET,
                    asset.asset_id,
                )
            ]
            if self._discovery_repository is not None and self._discovery_store is not None:
                discovered = await self._discovery_repository.list_for_story(
                    story.story_id,
                    script_revision=story.script.revision,
                )
                for asset in discovered:
                    candidate = asset.candidate
                    if (
                        asset.status is not VisualDiscoveryStatus.APPROVED
                        or candidate.kind is not CommonsMediaKind.IMAGE
                        or not candidate.publish_eligible
                        or asset.storage_key is None
                        or asset.sha256 is None
                        or asset.downloaded_size_bytes is None
                        or (
                            self._media_catalog is not None
                            and await self._media_catalog.is_archived(
                                MediaCatalogSourceKind.VISUAL_DISCOVERY,
                                asset.asset_id,
                            )
                        )
                    ):
                        continue
                    path = await self._discovery_store.resolve(asset.storage_key)
                    content_type = {
                        "image/png": "image/png",
                        "image/jpeg": "image/jpeg",
                        "image/webp": "image/webp",
                    }.get(candidate.mime_type.casefold())
                    if content_type is None:
                        continue
                    rendered.append(
                        VisualRenderAsset(
                            asset_id=asset.asset_id,
                            story_id=asset.story_id,
                            segment_id=asset.segment_id,
                            asset_type=VisualAssetType.IMAGE,
                            content_type=content_type,
                            filename=candidate.file_title.removeprefix("File:"),
                            local_path=str(path),
                            sha256=asset.sha256,
                            size_bytes=asset.downloaded_size_bytes,
                            width=candidate.width,
                            height=candidate.height,
                            source_label=(
                                f"{candidate.attribution.attribution_text} · "
                                f"{candidate.rights.license.value}"
                            ),
                            source_url=str(candidate.canonical_page_url),
                        )
                    )
            result[story.story_id] = tuple(rendered)
        return result

    async def _to_render_asset(
        self,
        story: Story,
        asset: StoredVisualAsset,
    ) -> VisualRenderAsset:
        path = await self._store.resolve(asset.storage_key)
        width, height = await inspect_raster_dimensions(path, asset.content_type)
        source_url = story.canonical_source_uri
        return VisualRenderAsset(
            asset_id=asset.asset_id,
            story_id=asset.story_id,
            segment_id=asset.segment_id,
            asset_type=(
                VisualAssetType.IMAGE
                if asset.origin is VisualAssetOrigin.EDITOR_UPLOAD
                else VisualAssetType.SOURCE_SCREENSHOT
            ),
            content_type=asset.content_type.value,
            filename=asset.filename,
            local_path=str(path),
            sha256=asset.sha256,
            size_bytes=asset.size_bytes,
            width=width,
            height=height,
            source_label=_source_label(story, source_url),
            source_url=source_url,
        )


def _source_label(story: Story, source_url: str | None) -> str:
    title = story.title or story.source.title or "Reviewed source"
    if source_url is None:
        return title
    host = (urlsplit(source_url).hostname or "").removeprefix("www.")
    return f"{title} · {host}" if host else title
