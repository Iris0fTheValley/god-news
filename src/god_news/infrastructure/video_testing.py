from __future__ import annotations

import asyncio
import copy
import hashlib
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from god_news.application.video_batches import require_video_transition
from god_news.domain.models import ScriptDocument, ScriptSegment, utc_now
from god_news.domain.video import (
    RemotionVideoProps,
    VideoBatch,
    VideoBatchStatus,
    VideoBatchStory,
    VideoInputAsset,
    VideoRenderArtifact,
    VideoRenderFailure,
    VideoRenderOutput,
)
from god_news.video_errors import (
    VideoBatchConflictError,
    VideoBatchNotFoundError,
    VideoStoryUnavailableError,
)


class InMemoryVideoBatchRepository:
    def __init__(self) -> None:
        self._batches: dict[UUID, VideoBatch] = {}
        self._claims: dict[UUID, UUID] = {}
        self._lock = asyncio.Lock()

    async def create(self, batch: VideoBatch) -> VideoBatch:
        batch = VideoBatch.model_validate(batch.model_dump())
        async with self._lock:
            unavailable = [
                story.story_id for story in batch.stories if story.story_id in self._claims
            ]
            if unavailable:
                raise VideoStoryUnavailableError(unavailable)
            if batch.batch_id in self._batches:
                raise VideoBatchConflictError("Video batch ID already exists.")
            self._batches[batch.batch_id] = copy.deepcopy(batch)
            for story in batch.stories:
                self._claims[story.story_id] = batch.batch_id
            return copy.deepcopy(batch)

    async def get(self, batch_id: UUID) -> VideoBatch:
        async with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                raise VideoBatchNotFoundError(batch_id)
            return copy.deepcopy(batch)

    async def list(
        self,
        *,
        status: VideoBatchStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[VideoBatch]:
        async with self._lock:
            batches = sorted(
                self._batches.values(),
                key=lambda item: (item.created_at, str(item.batch_id)),
                reverse=True,
            )
            if status is not None:
                batches = [batch for batch in batches if batch.status is status]
            return copy.deepcopy(batches[offset : offset + limit])

    async def unavailable_story_ids(self, story_ids: Sequence[UUID]) -> frozenset[UUID]:
        async with self._lock:
            return frozenset(story_id for story_id in story_ids if story_id in self._claims)

    async def save(self, batch: VideoBatch, *, expected_version: int) -> VideoBatch:
        batch = VideoBatch.model_validate(batch.model_dump())
        async with self._lock:
            current = self._batches.get(batch.batch_id)
            if current is None:
                raise VideoBatchNotFoundError(batch.batch_id)
            if current.version != expected_version:
                raise VideoBatchConflictError(
                    "Video batch changed concurrently; reload it and retry."
                )
            require_video_transition(current.status, batch.status)
            saved = VideoBatch.model_validate(
                batch.model_copy(update={"version": expected_version + 1}).model_dump()
            )
            if saved.status in {VideoBatchStatus.REJECTED, VideoBatchStatus.CANCELLED}:
                for story in saved.stories:
                    if self._claims.get(story.story_id) == saved.batch_id:
                        del self._claims[story.story_id]
            elif saved.status is VideoBatchStatus.RENDERED:
                for story in saved.stories:
                    if self._claims.get(story.story_id) != saved.batch_id:
                        raise VideoBatchConflictError("Video story claim was lost during render.")
            self._batches[saved.batch_id] = copy.deepcopy(saved)
            return copy.deepcopy(saved)

    async def recover_interrupted_rendering(self) -> Sequence[UUID]:
        async with self._lock:
            recovered: list[UUID] = []
            for batch_id, batch in list(self._batches.items()):
                if batch.status is not VideoBatchStatus.RENDERING:
                    continue
                failed = batch.model_copy(
                    update={
                        "status": VideoBatchStatus.FAILED,
                        "last_failure": VideoRenderFailure(
                            message="Rendering was interrupted by a previous service shutdown."
                        ),
                        "version": batch.version + 1,
                        "updated_at": utc_now(),
                    }
                )
                self._batches[batch_id] = VideoBatch.model_validate(failed.model_dump())
                recovered.append(batch_id)
            return recovered

    async def delete(self, batch_id: UUID) -> None:
        async with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                raise VideoBatchNotFoundError(batch_id)
            if batch.status in {
                VideoBatchStatus.PROCESSING_BATCH_TTS,
                VideoBatchStatus.RENDERING,
                VideoBatchStatus.RENDERED,
            }:
                raise VideoBatchConflictError(
                    "A batch with active synthesis, rendering, or rendered output cannot be "
                    "deleted because its claims are audit evidence."
                )
            for story in batch.stories:
                if self._claims.get(story.story_id) == batch.batch_id:
                    del self._claims[story.story_id]
            del self._batches[batch_id]

    async def protected_asset_paths(self) -> Sequence[Path]:
        active = {
            VideoBatchStatus.PENDING_TIMELINE_REVIEW,
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.RENDERING,
            VideoBatchStatus.FAILED,
        }
        async with self._lock:
            return [
                Path(asset.local_path)
                for batch in self._batches.values()
                if batch.status in active
                for asset in batch.input_assets
            ]

    async def healthcheck(self) -> None:
        return None


class DeterministicBatchNarrationComposer:
    """Offline fixture that proves merged narration is a separate artifact."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail_next = False

    @property
    def name(self) -> str:
        return "deterministic-offline-batch-narration"

    async def compose(
        self,
        *,
        batch_id: UUID,
        title: str,
        sources: Sequence[VideoBatchStory],
    ) -> ScriptDocument:
        del batch_id
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected deterministic batch narration failure")
        if not sources:
            raise ValueError("batch narration needs at least one source")
        languages = {source.script.spoken_language for source in sources}
        segments: list[ScriptSegment] = []
        for sequence, source in enumerate(sources):
            anchor = source.script.segments[0]
            bridge = "" if sequence == 0 else "Next, "
            segments.append(
                ScriptSegment(
                    sequence=sequence,
                    text=f"{bridge}{source.title}: {anchor.text}",
                    speaker_id=anchor.speaker_id,
                    emotion=anchor.emotion,
                    scene_transition=anchor.scene_transition,
                    speed=anchor.speed,
                    pitch=anchor.pitch,
                    visual_hint=anchor.visual_hint,
                )
            )
        return ScriptDocument(
            revision=1,
            title=title,
            language=next(iter(languages)) if len(languages) == 1 else "multilingual",
            segments=segments,
        )


class DeterministicBatchVideoRenderer:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir.expanduser().resolve()
        self.calls = 0
        self.fail_next = False

    @property
    def name(self) -> str:
        return "deterministic-offline-video"

    async def render(
        self,
        batch_id: UUID,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> VideoRenderArtifact:
        del input_assets
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected deterministic render failure")
        payload = b"god-news-deterministic-video\n" + props.model_dump_json().encode("utf-8")
        await asyncio.to_thread(self._output_dir.mkdir, parents=True, exist_ok=True)
        outputs: list[VideoRenderOutput] = []
        for profile in props.output_profiles:
            profile_payload = payload + b"\n" + profile.profile_id.value.encode("ascii")
            path = self._output_dir / f"{batch_id}-{profile.profile_id.value}.mp4"
            await asyncio.to_thread(path.write_bytes, profile_payload)
            outputs.append(
                VideoRenderOutput(
                    profile_id=profile.profile_id,
                    local_path=str(path),
                    size_bytes=len(profile_payload),
                    sha256=hashlib.sha256(profile_payload).hexdigest(),
                    width=profile.width,
                    height=profile.height,
                    fps=profile.fps,
                    duration_in_frames=max(
                        1,
                        round(props.manifest.total_duration_ms / 1_000 * profile.fps),
                    ),
                    video_codec="fixture",
                    audio_codec="fixture",
                )
            )
        return VideoRenderArtifact(
            renderer=self.name,
            outputs=outputs,
            rendered_at=utc_now(),
        )

    async def cleanup_interrupted(self, batch_ids: Sequence[UUID]) -> int:
        del batch_ids
        return 0
