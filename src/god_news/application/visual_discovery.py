from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from god_news.domain.models import Story, utc_now
from god_news.domain.ports import StoryRepository
from god_news.domain.visual_assets import ImageContentType
from god_news.domain.visual_discovery import (
    CommonsDiscoveryRequest,
    CommonsDiscoveryResult,
    CommonsMediaKind,
    CommonsVisualCandidate,
    PersistedVisualDiscoveryAsset,
    StageCommonsVisualRequest,
    VisualDiscoveryAssetView,
    VisualDiscoveryReviewRequest,
    VisualDiscoveryStatus,
)
from god_news.domain.visual_discovery_ports import (
    VisualDiscoveryRepository,
    VisualDiscoveryService,
    VisualDiscoveryStore,
)
from god_news.errors import ConcurrentWriteError, StoryInvariantError
from god_news.infrastructure.source_media_probe import FFprobeSourceVideoInspector
from god_news.infrastructure.visual_asset_store import inspect_raster_dimensions


class VisualDiscoveryApplication:
    """Stages official-provider assets only after re-resolving their metadata server-side."""

    def __init__(
        self,
        *,
        stories: StoryRepository,
        discovery: VisualDiscoveryService,
        repository: VisualDiscoveryRepository,
        store: VisualDiscoveryStore,
        client: httpx.AsyncClient,
        download_user_agent: str,
        max_download_bytes: int,
        ffprobe_command: Path | None = None,
    ) -> None:
        self._stories = stories
        self._discovery = discovery
        self._repository = repository
        self._store = store
        self._client = client
        self._download_user_agent = download_user_agent
        self._max_download_bytes = max_download_bytes
        self._video_inspector = (
            FFprobeSourceVideoInspector(ffprobe_command) if ffprobe_command is not None else None
        )

    async def search(self, request: CommonsDiscoveryRequest) -> CommonsDiscoveryResult:
        return await self._discovery.discover(request)

    async def stage(self, request: StageCommonsVisualRequest) -> VisualDiscoveryAssetView:
        story = await self._stories.get(request.story_id)
        self._require_current_segment(story, request)
        candidate = await self._resolve_candidate(request)
        if not candidate.publish_eligible:
            raise StoryInvariantError(
                story.story_id, "Commons asset rights are not eligible for publication."
            )
        _require_official_candidate(candidate)
        filename = candidate.file_title.removeprefix("File:")
        asset_id = uuid4()
        async with self._client.stream(
            "GET",
            str(candidate.direct_download_url),
            follow_redirects=False,
            headers={
                "User-Agent": self._download_user_agent,
                "Api-User-Agent": self._download_user_agent,
            },
        ) as response:
            storage_key, digest, size, path = await self._store.write_download(
                asset_id=asset_id,
                filename=filename,
                response=response,
                expected_max_bytes=self._max_download_bytes,
            )
        # Do not treat a claimed mimetype as enough evidence. Images need a
        # decodable signature/dimensions; videos retain the original and get a
        # deterministic ffprobe check if the runtime has one.
        try:
            probe_duration = await self._validate_download(candidate, path)
            asset = PersistedVisualDiscoveryAsset(
                asset_id=asset_id,
                story_id=story.story_id,
                segment_id=request.segment_id,
                script_revision=request.expected_script_revision,
                status=VisualDiscoveryStatus.STAGED,
                candidate=candidate,
                storage_key=storage_key,
                sha256=digest,
                downloaded_size_bytes=size,
                probed_duration_ms=probe_duration,
                created_at=utc_now(),
            )
            await self._repository.create(asset)
        except Exception:
            await self._store.remove(storage_key)
            raise
        return _view(asset)

    async def list(self, story_id: UUID) -> list[VisualDiscoveryAssetView]:
        story = await self._stories.get(story_id)
        if story.script is None:
            return []
        return [
            _view(asset)
            for asset in await self._repository.list_for_story(
                story_id, script_revision=story.script.revision
            )
        ]

    async def approve(
        self, asset_id: UUID, request: VisualDiscoveryReviewRequest
    ) -> VisualDiscoveryAssetView:
        asset = await self._repository.get(asset_id)
        story = await self._stories.get(asset.story_id)
        self._require_review_current(story, asset, request)
        if not asset.candidate.publish_eligible or asset.storage_key is None:
            raise StoryInvariantError(
                story.story_id, "Only downloaded rights-cleared assets can be approved."
            )
        return _view(
            await self._repository.set_status(
                asset_id, status=VisualDiscoveryStatus.APPROVED.value, review_note=request.note
            )
        )

    async def reject(
        self, asset_id: UUID, request: VisualDiscoveryReviewRequest
    ) -> VisualDiscoveryAssetView:
        asset = await self._repository.get(asset_id)
        story = await self._stories.get(asset.story_id)
        self._require_review_current(story, asset, request)
        return _view(
            await self._repository.set_status(
                asset_id, status=VisualDiscoveryStatus.REJECTED.value, review_note=request.note
            )
        )

    async def media_path(self, asset_id: UUID) -> tuple[VisualDiscoveryAssetView, Path]:
        asset = await self._repository.get(asset_id)
        if asset.status is not VisualDiscoveryStatus.APPROVED or asset.storage_key is None:
            raise StoryInvariantError(
                asset.story_id, "Only approved Commons assets can be used as media."
            )
        return _view(asset), await self._store.resolve(asset.storage_key)

    async def _resolve_candidate(
        self, request: StageCommonsVisualRequest
    ) -> CommonsVisualCandidate:
        result = await self._discovery.discover(
            CommonsDiscoveryRequest(file_title=request.file_title)
            if request.file_title is not None
            else CommonsDiscoveryRequest(page_id=request.page_id)
        )
        if len(result.candidates) != 1:
            raise ValueError("Commons identity did not resolve to exactly one candidate")
        return result.candidates[0]

    @staticmethod
    def _require_current_segment(story: Story, request: StageCommonsVisualRequest) -> None:
        if story.version != request.expected_story_version:
            raise ConcurrentWriteError(story.story_id)
        if story.script is None or story.script.revision != request.expected_script_revision:
            raise ConcurrentWriteError(story.story_id)
        if request.segment_id not in {segment.segment_id for segment in story.script.segments}:
            raise StoryInvariantError(
                story.story_id, "Visual asset must bind to a current script segment."
            )

    @staticmethod
    def _require_review_current(
        story: Story, asset: PersistedVisualDiscoveryAsset, request: VisualDiscoveryReviewRequest
    ) -> None:
        if story.version != request.expected_story_version:
            raise ConcurrentWriteError(story.story_id)
        if story.script is None or story.script.revision != asset.script_revision:
            raise StoryInvariantError(
                story.story_id, "The asset belongs to a stale script revision."
            )

    async def _validate_download(self, candidate: CommonsVisualCandidate, path: Path) -> int | None:
        if candidate.kind is CommonsMediaKind.IMAGE:
            content_type = {
                "image/png": ImageContentType.PNG,
                "image/jpeg": ImageContentType.JPEG,
                "image/webp": ImageContentType.WEBP,
            }.get(candidate.mime_type.casefold())
            if content_type is None:
                raise ValueError(
                    "Commons image MIME type is not supported for safe local inspection"
                )
            width, height = await inspect_raster_dimensions(path, content_type)
            if (width, height) != (candidate.width, candidate.height):
                raise ValueError("Commons image bytes do not match provider dimensions")
            return None
        # A complete native video remains available for a future B-roll library.
        if self._video_inspector is None:
            raise ValueError("ffprobe is required to stage Commons video assets")
        probe = await self._video_inspector.inspect(path)
        if (probe.width, probe.height) != (candidate.width, candidate.height):
            raise ValueError("Commons video bytes do not match provider dimensions")
        if abs(probe.duration_ms - (candidate.duration_ms or 0)) > 1_000:
            raise ValueError("Commons video bytes do not match provider duration")
        return probe.duration_ms


def _require_official_candidate(candidate: CommonsVisualCandidate) -> None:
    for url, host in (
        (candidate.canonical_page_url, "commons.wikimedia.org"),
        (candidate.direct_download_url, "upload.wikimedia.org"),
    ):
        parts = urlsplit(str(url))
        if parts.scheme != "https" or (parts.hostname or "").casefold() != host:
            raise ValueError("Commons provider returned a non-official HTTPS origin")


def _view(asset: PersistedVisualDiscoveryAsset) -> VisualDiscoveryAssetView:
    return VisualDiscoveryAssetView.model_validate(asset.model_dump(exclude={"storage_key"}))
