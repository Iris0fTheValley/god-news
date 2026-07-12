from __future__ import annotations

import asyncio
import builtins
import hashlib
import stat
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from god_news.domain.enums import ContentCategory, StoryStatus
from god_news.domain.models import ProductionManifest, Story, TimelineSegment, utc_now
from god_news.domain.video import (
    BgmRenderSpec,
    BgmTrack,
    CreateVideoBatch,
    HostVisualReservations,
    RemotionVideoProps,
    SubmitTimelineReview,
    TimelineReview,
    TimelineReviewDecision,
    VideoBatch,
    VideoBatchStatus,
    VideoBatchStory,
    VideoInputAsset,
    VideoInputAssetKind,
    VideoRenderFailure,
    is_video_batch_transition_allowed,
    render_input_sha256,
)
from god_news.domain.video_ports import (
    BatchVideoRenderer,
    BgmCatalog,
    HostRenderer,
    StoryManifestPool,
    VideoBatchRepository,
)
from god_news.errors import GodNewsError
from god_news.video_errors import (
    NoVideoCandidatesError,
    VideoBatchConflictError,
    VideoRenderingError,
    VideoStoryUnavailableError,
)

CATEGORY_ORDER: dict[ContentCategory, int] = {
    ContentCategory.KINDNESS: 0,
    ContentCategory.SHORT_VIDEO: 1,
    ContentCategory.CATS_DOGS: 2,
    ContentCategory.FORUM: 3,
}


class VideoBatchService:
    def __init__(
        self,
        *,
        story_pool: StoryManifestPool,
        repository: VideoBatchRepository,
        host_renderer: HostRenderer,
        video_renderer: BatchVideoRenderer,
        bgm_catalog: BgmCatalog,
        audio_root: Path,
        candidate_scan_limit: int = 1_000,
        asset_lifecycle_lock: asyncio.Lock | None = None,
    ) -> None:
        if candidate_scan_limit < 15:
            raise ValueError("candidate_scan_limit must be at least 15")
        self._story_pool = story_pool
        self._repository = repository
        self._host_renderer = host_renderer
        self._video_renderer = video_renderer
        self._bgm_catalog = bgm_catalog
        self._audio_root = audio_root.expanduser().resolve()
        self._candidate_scan_limit = candidate_scan_limit
        self._asset_lifecycle_lock = asset_lifecycle_lock or asyncio.Lock()
        self._render_locks: dict[UUID, asyncio.Lock] = {}

    async def list_bgm(self) -> Sequence[BgmTrack]:
        return await self._bgm_catalog.list()

    async def create(self, request: CreateVideoBatch) -> VideoBatch:
        async with self._asset_lifecycle_lock:
            return await self._create_locked(request)

    async def _create_locked(self, request: CreateVideoBatch) -> VideoBatch:
        selected = await self._select_stories(request)
        ordered = sorted(selected, key=self._story_order_key)
        host = await self._host_renderer.prepare(ordered)
        bgm = None
        if request.bgm_track_id is not None:
            bgm = await self._bgm_catalog.resolve(
                request.bgm_track_id,
                volume=request.bgm_volume,
                loop=request.bgm_loop,
            )

        batch_id = uuid4()
        reserved_at = utc_now()
        stories = await self._build_batch_stories(ordered, reserved_at=reserved_at)
        props = self._build_remotion_props(
            batch_id=batch_id,
            title=request.title,
            subtitle=request.subtitle,
            stories=stories,
            bgm=(bgm.render_spec() if bgm is not None else None),
            host=host,
        )
        input_assets = await asyncio.to_thread(self._snapshot_input_assets, props)
        batch = VideoBatch(
            batch_id=batch_id,
            title=request.title,
            subtitle=request.subtitle,
            stories=stories,
            bgm=bgm,
            remotion_props=props,
            input_assets=input_assets,
            render_input_sha256=self._render_hash(props, input_assets),
        )
        return await self._repository.create(batch)

    async def get(self, batch_id: UUID) -> VideoBatch:
        return await self._repository.get(batch_id)

    async def list_batches(
        self,
        *,
        status: VideoBatchStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[VideoBatch]:
        return await self._repository.list(status=status, limit=limit, offset=offset)

    async def submit_timeline_review(
        self,
        batch_id: UUID,
        submission: SubmitTimelineReview,
    ) -> VideoBatch:
        batch = await self._repository.get(batch_id)
        self._require_version(batch, submission.expected_batch_version)
        if batch.status is not VideoBatchStatus.PENDING_TIMELINE_REVIEW:
            raise VideoBatchConflictError(
                f"Timeline review is not allowed while batch is {batch.status.value}."
            )

        ordered = self._review_order(batch, submission.story_order)
        stories = self._resequence_stories(ordered)
        props = self._build_remotion_props(
            batch_id=batch.batch_id,
            title=batch.title,
            subtitle=batch.subtitle,
            stories=stories,
            bgm=batch.remotion_props.bgm,
            host=batch.remotion_props.visual_reservations,
        )
        review = TimelineReview(
            reviewer_id=submission.reviewer_id,
            decision=submission.decision,
            reviewed_batch_version=batch.version,
            story_order=[story.story_id for story in stories],
            note=submission.note,
        )
        target = (
            VideoBatchStatus.READY_TO_RENDER
            if submission.decision is TimelineReviewDecision.APPROVE
            else VideoBatchStatus.REJECTED
        )
        updated = batch.model_copy(
            update={
                "status": target,
                "stories": stories,
                "remotion_props": props,
                "render_input_sha256": self._render_hash(props, batch.input_assets),
                "timeline_review": review,
                "updated_at": utc_now(),
            }
        )
        return await self._repository.save(updated, expected_version=batch.version)

    async def render(self, batch_id: UUID, *, expected_version: int) -> VideoBatch:
        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            self._require_version(batch, expected_version)
            if batch.status not in {VideoBatchStatus.READY_TO_RENDER, VideoBatchStatus.FAILED}:
                raise VideoBatchConflictError(
                    f"Rendering is not allowed while batch is {batch.status.value}."
                )
            await asyncio.to_thread(self._verify_input_assets, batch.input_assets)

            running = batch.model_copy(
                update={
                    "status": VideoBatchStatus.RENDERING,
                    "last_failure": None,
                    "updated_at": utc_now(),
                }
            )
            running = await self._repository.save(running, expected_version=batch.version)
            try:
                artifact = await self._video_renderer.render(
                    running.batch_id,
                    running.remotion_props,
                )
            except Exception as exc:
                failed = running.model_copy(
                    update={
                        "status": VideoBatchStatus.FAILED,
                        "last_failure": VideoRenderFailure(message=self._failure_message(exc)),
                        "updated_at": utc_now(),
                    }
                )
                await self._repository.save(failed, expected_version=running.version)
                if isinstance(exc, GodNewsError):
                    raise
                raise VideoRenderingError("Local video rendering failed.") from exc

            used_at = artifact.rendered_at
            rendered = running.model_copy(
                update={
                    "status": VideoBatchStatus.RENDERED,
                    "stories": [
                        story.model_copy(update={"used_at": used_at})
                        for story in running.stories
                    ],
                    "artifact": artifact,
                    "last_failure": None,
                    "updated_at": used_at,
                }
            )
            return await self._repository.save(rendered, expected_version=running.version)

    async def cancel(self, batch_id: UUID) -> VideoBatch:
        """Release a not-yet-rendered batch without pretending to kill a renderer.

        A concrete future renderer must expose an explicit subprocess cancellation
        contract before active RENDERING work can be stopped safely.
        """
        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            if batch.status is VideoBatchStatus.CANCELLED:
                return batch
            if batch.status is VideoBatchStatus.RENDERED:
                raise VideoBatchConflictError("Rendered batches are immutable audit evidence.")
            if batch.status is VideoBatchStatus.RENDERING:
                raise VideoBatchConflictError(
                    "The active renderer has no safe cancellation contract; wait for it to finish."
                )
            if batch.status is VideoBatchStatus.REJECTED:
                return batch
            cancelled = batch.model_copy(
                update={
                    "status": VideoBatchStatus.CANCELLED,
                    "last_failure": None,
                    "updated_at": utc_now(),
                }
            )
            return await self._repository.save(cancelled, expected_version=batch.version)

    async def delete(self, batch_id: UUID) -> None:
        async with self._lock_for(batch_id):
            await self._repository.delete(batch_id)

    async def _select_stories(self, request: CreateVideoBatch) -> builtins.list[Story]:
        if request.story_ids:
            stories = [await self._story_pool.get(story_id) for story_id in request.story_ids]
        else:
            stories = list(
                await self._story_pool.list(
                    status=StoryStatus.DONE,
                    limit=self._candidate_scan_limit,
                    offset=0,
                )
            )
        eligible = [story for story in stories if self._is_eligible(story)]
        if request.story_ids and len(eligible) != len(stories):
            ineligible = [story.story_id for story in stories if not self._is_eligible(story)]
            raise VideoBatchConflictError(
                "Explicit stories must be DONE, complete, and accepted video candidates: "
                + ", ".join(str(item) for item in sorted(ineligible, key=str))
            )
        unavailable = await self._repository.unavailable_story_ids(
            [story.story_id for story in eligible]
        )
        if request.story_ids and unavailable:
            raise VideoStoryUnavailableError(list(unavailable))
        available = [story for story in eligible if story.story_id not in unavailable]
        available.sort(key=self._story_order_key)
        selected = available[: request.max_stories]
        if not selected:
            raise NoVideoCandidatesError()
        return selected

    @staticmethod
    def _is_eligible(story: Story) -> bool:
        return bool(
            story.status is StoryStatus.DONE
            and story.translation is not None
            and story.translation.screening.candidate_recommendation
            and story.script is not None
            and story.audio is not None
        )

    @staticmethod
    def _story_order_key(story: Story) -> tuple[int, datetime, str]:
        assert story.translation is not None
        created = story.created_at.astimezone(UTC)
        return (
            CATEGORY_ORDER[story.translation.screening.category],
            created,
            str(story.story_id),
        )

    async def _build_batch_stories(
        self,
        stories: Sequence[Story],
        *,
        reserved_at: datetime,
    ) -> builtins.list[VideoBatchStory]:
        result: builtins.list[VideoBatchStory] = []
        cursor = 0
        for sequence, story in enumerate(stories):
            assert story.translation is not None
            manifest = await self._story_pool.production_manifest(story.story_id)
            manifest = await asyncio.to_thread(self._resolve_audio_paths, manifest)
            end = cursor + manifest.total_duration_ms
            result.append(
                VideoBatchStory(
                    sequence=sequence,
                    story_id=story.story_id,
                    story_version=story.version,
                    category=story.translation.screening.category,
                    title=story.source.title,
                    manifest=manifest,
                    chapter_start_ms=cursor,
                    chapter_end_ms=end,
                    reserved_at=reserved_at,
                )
            )
            cursor = end
        return result

    def _resolve_audio_paths(self, manifest: ProductionManifest) -> ProductionManifest:
        timeline: builtins.list[TimelineSegment] = []
        for segment in manifest.timeline:
            supplied = Path(segment.audio_path).expanduser()
            path = (
                supplied.resolve()
                if supplied.is_absolute()
                else (self._audio_root / supplied).resolve()
            )
            try:
                path.relative_to(self._audio_root)
            except ValueError as exc:
                raise VideoBatchConflictError(
                    f"Story {manifest.story_id} contains audio outside the configured output root."
                ) from exc
            if not path.is_file():
                raise VideoBatchConflictError(
                    f"Story {manifest.story_id} references a missing local audio clip."
                )
            timeline.append(segment.model_copy(update={"audio_path": str(path)}))
        return manifest.model_copy(update={"timeline": timeline})

    @staticmethod
    def _resequence_stories(
        stories: Sequence[VideoBatchStory],
    ) -> builtins.list[VideoBatchStory]:
        result: builtins.list[VideoBatchStory] = []
        cursor = 0
        for sequence, story in enumerate(stories):
            end = cursor + story.manifest.total_duration_ms
            result.append(
                story.model_copy(
                    update={
                        "sequence": sequence,
                        "chapter_start_ms": cursor,
                        "chapter_end_ms": end,
                    }
                )
            )
            cursor = end
        return result

    @staticmethod
    def _build_remotion_props(
        *,
        batch_id: UUID,
        title: str,
        subtitle: str | None,
        stories: Sequence[VideoBatchStory],
        bgm: BgmRenderSpec | None,
        host: HostVisualReservations,
    ) -> RemotionVideoProps:
        timeline: builtins.list[TimelineSegment] = []
        cursor = 0
        seen_segments: set[UUID] = set()
        languages = {story.manifest.language for story in stories}
        for story in stories:
            for segment in story.manifest.timeline:
                if segment.segment_id in seen_segments:
                    raise VideoBatchConflictError(
                        "Story manifests contain duplicate segment IDs."
                    )
                seen_segments.add(segment.segment_id)
                duration = segment.end_ms - segment.start_ms
                timeline.append(
                    segment.model_copy(
                        update={
                            "sequence": len(timeline),
                            "start_ms": cursor,
                            "end_ms": cursor + duration,
                        }
                    )
                )
                cursor += duration
        manifest = ProductionManifest(
            story_id=batch_id,
            script_revision=1,
            language=next(iter(languages)) if len(languages) == 1 else "multilingual",
            total_duration_ms=cursor,
            timeline=timeline,
        )
        return RemotionVideoProps(
            manifest=manifest,
            title=title,
            subtitle=subtitle,
            bgm=bgm,
            visual_reservations=host,
        )

    @staticmethod
    def _review_order(
        batch: VideoBatch,
        requested: Sequence[UUID] | None,
    ) -> builtins.list[VideoBatchStory]:
        if requested is None:
            return list(batch.stories)
        current = {story.story_id: story for story in batch.stories}
        if set(requested) != set(current) or len(requested) != len(current):
            raise VideoBatchConflictError(
                "Reviewed story_order must contain every batch story exactly once."
            )
        return [current[story_id] for story_id in requested]

    @staticmethod
    def _render_hash(props: RemotionVideoProps, assets: list[VideoInputAsset]) -> str:
        return render_input_sha256(props, assets)

    @staticmethod
    def _snapshot_input_assets(props: RemotionVideoProps) -> list[VideoInputAsset]:
        candidates: list[tuple[VideoInputAssetKind, str]] = [
            (VideoInputAssetKind.AUDIO, segment.audio_path)
            for segment in props.manifest.timeline
        ]
        if props.bgm is not None:
            candidates.append((VideoInputAssetKind.BGM, props.bgm.local_path))
        seen: set[tuple[VideoInputAssetKind, str]] = set()
        assets: list[VideoInputAsset] = []
        for kind, raw_path in candidates:
            key = (kind, raw_path)
            if key in seen:
                continue
            seen.add(key)
            assets.append(VideoBatchService._snapshot_asset(kind, raw_path))
        return assets

    @staticmethod
    def _snapshot_asset(kind: VideoInputAssetKind, raw_path: str) -> VideoInputAsset:
        path = Path(raw_path).expanduser().resolve(strict=True)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise VideoBatchConflictError("A reviewed video input is not a regular non-empty file.")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise VideoBatchConflictError(
                "A video input changed while its review snapshot was created."
            )
        return VideoInputAsset(
            kind=kind,
            local_path=str(path),
            sha256=digest.hexdigest(),
            size_bytes=before.st_size,
        )

    @staticmethod
    def _verify_input_assets(assets: list[VideoInputAsset]) -> None:
        for asset in assets:
            current = VideoBatchService._snapshot_asset(asset.kind, asset.local_path)
            if current.sha256 != asset.sha256 or current.size_bytes != asset.size_bytes:
                raise VideoBatchConflictError(
                    "A reviewed video input changed; submit the timeline for review again."
                )

    @staticmethod
    def _require_version(batch: VideoBatch, expected: int) -> None:
        if batch.version != expected:
            raise VideoBatchConflictError(
                "Video batch changed concurrently; reload it and retry."
            )

    @staticmethod
    def _failure_message(exc: Exception) -> str:
        if isinstance(exc, GodNewsError):
            return exc.public_message
        return f"{type(exc).__name__}: local render failed"

    def _lock_for(self, batch_id: UUID) -> asyncio.Lock:
        lock = self._render_locks.get(batch_id)
        if lock is None:
            lock = asyncio.Lock()
            self._render_locks[batch_id] = lock
        return lock


def require_video_transition(current: VideoBatchStatus, target: VideoBatchStatus) -> None:
    if not is_video_batch_transition_allowed(current, target):
        raise VideoBatchConflictError(
            f"Video batch cannot transition from {current.value} to {target.value}."
        )
