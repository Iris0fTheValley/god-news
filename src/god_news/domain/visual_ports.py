from __future__ import annotations

from collections.abc import AsyncIterable, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.visual_assets import ImageContentType, StoredVisualAsset


class VisualAssetRepository(Protocol):
    """Durable bindings between stories, script revisions, and raster assets."""

    async def list_for_script(
        self,
        story_id: UUID,
        *,
        script_revision: int,
    ) -> Sequence[StoredVisualAsset]: ...

    async def get(self, story_id: UUID, asset_id: UUID) -> StoredVisualAsset: ...

    async def replace_segment_upload(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]: ...

    async def delete_segment_upload(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        script_revision: int,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]: ...

    async def replace_source_screenshot(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]: ...


class VisualAssetStore(Protocol):
    """Content-addressed-by-reference local media store; never exposes paths to clients."""

    async def write(
        self,
        *,
        story_id: UUID,
        asset_id: UUID,
        content_type: ImageContentType,
        body: AsyncIterable[bytes],
    ) -> tuple[str, str, int]:
        """Return opaque storage key, SHA-256, and byte count after validation."""

    async def remove(self, storage_key: str) -> None: ...

    async def resolve(self, storage_key: str) -> Path: ...
