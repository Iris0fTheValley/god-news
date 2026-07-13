from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterable
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from god_news.domain.enums import StoryStatus
from god_news.domain.models import Story, utc_now
from god_news.domain.ports import StoryRepository
from god_news.domain.visual_assets import (
    DeleteSegmentVisualAssetRequest,
    ImageContentType,
    SegmentVisualAssetBinding,
    StoredVisualAsset,
    StoryVisualAssets,
    UploadSegmentVisualAssetRequest,
    VisualAsset,
    VisualAssetMutation,
    VisualAssetOrigin,
)
from god_news.domain.visual_ports import VisualAssetRepository, VisualAssetStore
from god_news.errors import (
    ArtifactNotReadyError,
    ConcurrentWriteError,
    StoryInvariantError,
    VisualAssetNotFoundError,
    VisualAssetStorageError,
    VisualAssetUploadError,
)

logger = logging.getLogger(__name__)

_SAFE_SOURCE_SCHEMES = frozenset({"https"})
_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain"})
_UNSAFE_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_EXTENSION_BY_CONTENT_TYPE = {
    ImageContentType.PNG: ".png",
    ImageContentType.JPEG: ".jpg",
    ImageContentType.WEBP: ".webp",
}


class VisualAssetService:
    """Application boundary for revision-scoped script visuals.

    Assets are intentionally external to ``ScriptSegment.visual_hint``: a hint
    remains free editorial text, while a stored visual is a durable ID-bound
    media object.  The service performs script/version checks before a file is
    bound and removes replaced files only after the database transaction has
    committed.
    """

    def __init__(
        self,
        *,
        stories: StoryRepository,
        repository: VisualAssetRepository,
        store: VisualAssetStore,
        asset_lifecycle_lock: asyncio.Lock | None = None,
    ) -> None:
        self._stories = stories
        self._repository = repository
        self._store = store
        self._asset_lifecycle_lock = asset_lifecycle_lock or asyncio.Lock()

    async def list(self, story_id: UUID) -> StoryVisualAssets:
        story = await self._stories.get(story_id)
        script = story.script
        if script is None:
            raise ArtifactNotReadyError(story_id, "Script is not ready for visual assets.")
        stored = await self._repository.list_for_script(
            story_id,
            script_revision=script.revision,
        )
        source_screenshots = [
            asset
            for asset in stored
            if asset.origin is VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT
        ]
        uploads = [
            asset for asset in stored if asset.origin is VisualAssetOrigin.EDITOR_UPLOAD
        ]
        return StoryVisualAssets(
            story_id=story_id,
            story_version=story.version,
            script_revision=script.revision,
            source_page_url=_safe_source_page_url(story),
            # A list response never invents a screenshot from the source URL.
            source_page_screenshot=(
                _public(source_screenshots[-1]) if source_screenshots else None
            ),
            segment_assets=[
                SegmentVisualAssetBinding(segment_id=asset.segment_id, asset=_public(asset))
                for asset in uploads
                if asset.segment_id is not None
            ],
        )

    async def upload_segment(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        request: UploadSegmentVisualAssetRequest,
        declared_content_type: str | None,
        body: AsyncIterable[bytes],
    ) -> VisualAssetMutation:
        async with self._asset_lifecycle_lock:
            return await self._upload_segment_locked(
                story_id=story_id,
                segment_id=segment_id,
                request=request,
                declared_content_type=declared_content_type,
                body=body,
            )

    async def _upload_segment_locked(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        request: UploadSegmentVisualAssetRequest,
        declared_content_type: str | None,
        body: AsyncIterable[bytes],
    ) -> VisualAssetMutation:
        story = await self._stories.get(story_id)
        self._require_editable_segment(
            story,
            segment_id=segment_id,
            expected_story_version=request.expected_story_version,
            expected_script_revision=request.expected_script_revision,
        )
        content_type = _parse_content_type(story_id, declared_content_type)
        asset_id = uuid4()
        storage_key, digest, size_bytes = await self._store.write(
            story_id=story_id,
            asset_id=asset_id,
            content_type=content_type,
            body=body,
        )
        asset = StoredVisualAsset(
            asset_id=asset_id,
            story_id=story_id,
            segment_id=segment_id,
            script_revision=request.expected_script_revision,
            origin=VisualAssetOrigin.EDITOR_UPLOAD,
            content_type=content_type,
            filename=_safe_filename(request.filename, content_type),
            storage_key=storage_key,
            sha256=digest,
            size_bytes=size_bytes,
        )
        try:
            replaced, story_version = await self._repository.replace_segment_upload(
                asset,
                expected_story_version=request.expected_story_version,
            )
        except Exception:
            await self._store.remove(storage_key)
            raise
        await self._discard_replaced(replaced)
        return VisualAssetMutation(asset=_public(asset), story_version=story_version)

    async def delete_segment(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        request: DeleteSegmentVisualAssetRequest,
    ) -> None:
        async with self._asset_lifecycle_lock:
            await self._delete_segment_locked(
                story_id=story_id,
                segment_id=segment_id,
                request=request,
            )

    async def _delete_segment_locked(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        request: DeleteSegmentVisualAssetRequest,
    ) -> None:
        story = await self._stories.get(story_id)
        self._require_editable_segment(
            story,
            segment_id=segment_id,
            expected_story_version=request.expected_story_version,
            expected_script_revision=request.expected_script_revision,
        )
        removed, _story_version = await self._repository.delete_segment_upload(
            story_id=story_id,
            segment_id=segment_id,
            script_revision=request.expected_script_revision,
            expected_story_version=request.expected_story_version,
        )
        if removed is None:
            raise VisualAssetNotFoundError(story_id)
        await self._store.remove(removed.storage_key)

    async def media_path(self, story_id: UUID, asset_id: UUID) -> tuple[VisualAsset, Path]:
        story = await self._stories.get(story_id)
        asset = await self._repository.get(story_id, asset_id)
        if asset.origin is VisualAssetOrigin.EDITOR_UPLOAD:
            script = story.script
            if (
                script is None
                or asset.script_revision != script.revision
                or asset.segment_id not in {segment.segment_id for segment in script.segments}
            ):
                # Historical revision assets are retained for audit/retention,
                # but must not be addressable as active scene media.
                raise VisualAssetNotFoundError(story_id)
        try:
            path = await self._store.resolve(asset.storage_key)
        except (FileNotFoundError, ValueError):
            raise VisualAssetNotFoundError(story_id) from None
        except OSError as exc:
            raise VisualAssetStorageError(story_id, "Visual asset path is invalid.") from exc
        return _public(asset), path

    async def register_source_screenshot(
        self,
        *,
        story_id: UUID,
        expected_story_version: int,
        filename: str,
        declared_content_type: str | None,
        body: AsyncIterable[bytes],
    ) -> VisualAssetMutation:
        async with self._asset_lifecycle_lock:
            return await self._register_source_screenshot_locked(
                story_id=story_id,
                expected_story_version=expected_story_version,
                filename=filename,
                declared_content_type=declared_content_type,
                body=body,
            )

    async def _register_source_screenshot_locked(
        self,
        *,
        story_id: UUID,
        expected_story_version: int,
        filename: str,
        declared_content_type: str | None,
        body: AsyncIterable[bytes],
    ) -> VisualAssetMutation:
        """Internal seam for a future capture worker after it has captured pixels.

        This is deliberately not exposed as a browser route. A caller must
        capture the source page through an explicit, policy-governed adapter
        before registering bytes here; a source URL alone is never converted
        into a false screenshot asset.
        """

        story = await self._stories.get(story_id)
        if story.version != expected_story_version:
            raise ConcurrentWriteError(story_id)
        if _safe_source_page_url(story) is None:
            raise StoryInvariantError(story_id, "Story has no safe HTTPS source-page candidate.")
        content_type = _parse_content_type(story_id, declared_content_type)
        asset_id = uuid4()
        storage_key, digest, size_bytes = await self._store.write(
            story_id=story_id,
            asset_id=asset_id,
            content_type=content_type,
            body=body,
        )
        asset = StoredVisualAsset(
            asset_id=asset_id,
            story_id=story_id,
            origin=VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT,
            content_type=content_type,
            filename=_safe_filename(filename, content_type),
            storage_key=storage_key,
            sha256=digest,
            size_bytes=size_bytes,
            created_at=utc_now(),
        )
        try:
            replaced, story_version = await self._repository.replace_source_screenshot(
                asset,
                expected_story_version=expected_story_version,
            )
        except Exception:
            await self._store.remove(storage_key)
            raise
        await self._discard_replaced(replaced)
        return VisualAssetMutation(asset=_public(asset), story_version=story_version)

    @staticmethod
    def _require_editable_segment(
        story: Story,
        *,
        segment_id: UUID,
        expected_story_version: int,
        expected_script_revision: int,
    ) -> None:
        if story.version != expected_story_version:
            raise ConcurrentWriteError(story.story_id)
        if story.status not in {StoryStatus.SCRIPT_READY, StoryStatus.PENDING_SECOND_REVIEW}:
            raise StoryInvariantError(
                story.story_id,
                "Visual assets can only change during script or final review.",
            )
        if story.script is None:
            raise ArtifactNotReadyError(story.story_id, "Script is not ready for visual assets.")
        if story.script.revision != expected_script_revision:
            raise ConcurrentWriteError(story.story_id)
        if segment_id not in {segment.segment_id for segment in story.script.segments}:
            raise StoryInvariantError(
                story.story_id,
                "Visual asset must bind to a current script segment.",
            )

    async def _discard_replaced(self, asset: StoredVisualAsset | None) -> None:
        if asset is None:
            return
        await self._store.remove(asset.storage_key)
        logger.info("replaced visual asset removed asset_id=%s", asset.asset_id)


def _public(asset: StoredVisualAsset) -> VisualAsset:
    return VisualAsset.model_validate(asset.model_dump(exclude={"storage_key"}))


def _parse_content_type(story_id: UUID, raw: str | None) -> ImageContentType:
    normalized = (raw or "").split(";", 1)[0].strip().casefold()
    try:
        return ImageContentType(normalized)
    except ValueError as exc:
        raise VisualAssetUploadError(
            story_id,
            "Only PNG, JPEG, and WebP raster uploads are accepted.",
        ) from exc


def _safe_filename(raw: str, content_type: ImageContentType) -> str:
    candidate = PurePosixPath(raw.replace("\\", "/")).name.strip()
    candidate = re.sub(r'[\x00-\x1f<>:"/\\\\|?*]', "_", candidate).strip(". ")
    if not candidate:
        candidate = "visual"
    candidate = candidate[:240]
    suffix = _EXTENSION_BY_CONTENT_TYPE[content_type]
    if not candidate.casefold().endswith(suffix):
        candidate = f"{candidate}{suffix}"
    return candidate[:255]


def _safe_source_page_url(story: Story) -> str | None:
    candidate = story.canonical_source_uri
    if candidate is None:
        return None
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() not in _SAFE_SOURCE_SCHEMES
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or hostname in _LOCAL_HOSTS
        or hostname.endswith(_UNSAFE_HOST_SUFFIXES)
    ):
        return None
    # A URL literal bypasses DNS policy checks and may point to a private
    # service. Only expose named public HTTPS origins as browser candidates.
    if hostname.replace(".", "").isdigit() or ":" in hostname:
        return None
    return candidate
