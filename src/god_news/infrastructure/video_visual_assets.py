from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit
from uuid import UUID

from god_news.domain.models import Story
from god_news.domain.video import VisualAssetType, VisualRenderAsset
from god_news.domain.visual_assets import (
    StoredVisualAsset,
    VisualAssetOrigin,
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
    ) -> None:
        self._repository = repository
        self._store = store

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
            result[story.story_id] = tuple(
                [await self._to_render_asset(story, asset) for asset in assets]
            )
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
