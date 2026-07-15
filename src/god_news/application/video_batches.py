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
from god_news.domain.models import (
    AudioBundle,
    ProductionManifest,
    ScriptDocument,
    Story,
    TimelineSegment,
    utc_now,
)
from god_news.domain.ports import SpeechSynthesizer
from god_news.domain.video import (
    BatchNarrationArtifact,
    BatchNarrationFailure,
    BatchNarrationSourceEvidence,
    BgmRenderSpec,
    BgmTrack,
    CreateVideoBatch,
    HostVisualReservations,
    NarrationReview,
    NarrationReviewDecision,
    RemotionVideoProps,
    SubmitNarrationReview,
    SubmitTimelineReview,
    SynthesizeBatchNarration,
    TimelineReview,
    TimelineReviewDecision,
    VideoBatch,
    VideoBatchStatus,
    VideoBatchStory,
    VideoInputAsset,
    VideoInputAssetKind,
    VideoRenderFailure,
    is_video_batch_transition_allowed,
    model_sha256,
    narration_source_evidence_sha256,
    render_input_sha256,
)
from god_news.domain.video_ports import (
    BatchNarrationComposer,
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
    VideoNarrationSynthesisError,
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
    """Review-gated orchestration for one merged, multi-story narration.

    Source stories are claimed once and retained as immutable provenance.  The
    compositor produces a separate batch script; only its manually synthesized
    audio is ever turned into Remotion props or file snapshots.
    """

    def __init__(
        self,
        *,
        story_pool: StoryManifestPool,
        repository: VideoBatchRepository,
        host_renderer: HostRenderer,
        narration_composer: BatchNarrationComposer,
        synthesizer: SpeechSynthesizer,
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
        self._narration_composer = narration_composer
        self._synthesizer = synthesizer
        self._video_renderer = video_renderer
        self._bgm_catalog = bgm_catalog
        self._audio_root = audio_root.expanduser().resolve()
        self._candidate_scan_limit = candidate_scan_limit
        self._asset_lifecycle_lock = asset_lifecycle_lock or asyncio.Lock()
        self._batch_locks: dict[UUID, asyncio.Lock] = {}

    async def list_bgm(self) -> Sequence[BgmTrack]:
        return await self._bgm_catalog.list()

    async def recover_interrupted(self) -> int:
        """Make crash-orphaned render work retryable before accepting traffic."""

        recovered = await self._repository.recover_interrupted_rendering()
        await self._video_renderer.cleanup_interrupted(recovered)
        return len(recovered)

    async def create(self, request: CreateVideoBatch) -> VideoBatch:
        """Reserve DONE stories and compose a *draft* batch narration.

        No source audio is copied into a render plan here.  If the composer is
        unavailable, no batch or source claim is persisted, keeping retry and
        replacement semantics honest.
        """

        async with self._asset_lifecycle_lock:
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
            stories = await self._build_batch_stories(ordered, reserved_at=utc_now())
            composed_script = await self._narration_composer.compose(
                batch_id=batch_id,
                title=request.title,
                sources=stories,
            )
            # A new batch owns its own revision history.  Composer internals
            # cannot accidentally leak a source-story revision into it.
            script = composed_script.model_copy(update={"revision": 1})
            evidence = self._source_evidence(stories)
            narration = BatchNarrationArtifact(
                source_evidence=evidence,
                source_evidence_sha256=narration_source_evidence_sha256(evidence),
                script=script,
            )
            batch = VideoBatch(
                batch_id=batch_id,
                title=request.title,
                subtitle=request.subtitle,
                stories=stories,
                narration=narration,
                bgm=bgm,
                visual_reservations=host,
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

    async def submit_narration_review(
        self,
        batch_id: UUID,
        submission: SubmitNarrationReview,
    ) -> VideoBatch:
        """Approve, revise, or reject the merged script before batch TTS.

        A revision from the post-TTS timeline gate is intentionally allowed: it
        clears derived media and returns to script review rather than letting a
        stale audio bundle survive an editorial change.
        """

        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            self._require_version(batch, submission.expected_batch_version)
            self._require_narration_review_state(batch, submission.decision)

            narration = batch.narration
            script = narration.script
            target = batch.status
            timeline_review = batch.timeline_review
            remotion_props = batch.remotion_props
            input_assets = batch.input_assets
            render_hash = batch.render_input_sha256
            if submission.decision is NarrationReviewDecision.APPROVE:
                target = VideoBatchStatus.PENDING_BATCH_TTS
            elif submission.decision is NarrationReviewDecision.REJECT:
                target = VideoBatchStatus.REJECTED
            else:
                assert submission.revised_script is not None
                script = submission.revised_script.model_copy(
                    update={"revision": narration.script.revision + 1}
                )
                narration = narration.model_copy(
                    update={
                        "script": script,
                        "audio": None,
                        "manifest": None,
                        "synthesized_at": None,
                    }
                )
                target = VideoBatchStatus.PENDING_NARRATION_REVIEW
                timeline_review = None
                remotion_props = None
                input_assets = []
                render_hash = None

            review = NarrationReview(
                reviewer_id=submission.reviewer_id,
                decision=submission.decision,
                reviewed_batch_version=batch.version,
                script_revision=script.revision,
                script_sha256=model_sha256(script),
                note=submission.note,
            )
            updated = batch.model_copy(
                update={
                    "status": target,
                    "narration": narration,
                    "narration_reviews": [*batch.narration_reviews, review],
                    "timeline_review": timeline_review,
                    "remotion_props": remotion_props,
                    "input_assets": input_assets,
                    "render_input_sha256": render_hash,
                    "narration_failure": None,
                    "last_failure": None,
                    "updated_at": utc_now(),
                }
            )
            return await self._repository.save(updated, expected_version=batch.version)

    async def synthesize_narration(
        self,
        batch_id: UUID,
        request: SynthesizeBatchNarration,
    ) -> VideoBatch:
        """Start local batch TTS only after explicit narration approval."""

        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            self._require_version(batch, request.expected_batch_version)
            if batch.status is not VideoBatchStatus.PENDING_BATCH_TTS:
                raise VideoBatchConflictError(
                    f"Batch TTS is not allowed while batch is {batch.status.value}."
                )
            running = batch.model_copy(
                update={
                    "status": VideoBatchStatus.PROCESSING_BATCH_TTS,
                    "narration_failure": None,
                    "updated_at": utc_now(),
                }
            )
            running = await self._repository.save(running, expected_version=batch.version)

        try:
            audio = await self._synthesizer.synthesize(
                running.batch_id,
                running.narration.script,
            )
            audio = await asyncio.to_thread(self._resolve_batch_audio_paths, audio)
            self._validate_synthesized_audio(running.narration.script, audio)
            manifest = self._build_merged_manifest(
                batch_id=running.batch_id,
                script=running.narration.script,
                audio=audio,
            )
            props = self._build_remotion_props(
                batch_id=running.batch_id,
                title=running.title,
                subtitle=running.subtitle,
                manifest=manifest,
                bgm=(running.bgm.render_spec() if running.bgm is not None else None),
                host=running.visual_reservations,
            )
            input_assets = await asyncio.to_thread(self._snapshot_input_assets, props)
            self._validate_audio_snapshot_evidence(audio, input_assets)
        except Exception as exc:
            return await self._record_narration_failure(running, exc)

        async with self._lock_for(batch_id):
            current = await self._repository.get(batch_id)
            if (
                current.status is not VideoBatchStatus.PROCESSING_BATCH_TTS
                or current.version != running.version
            ):
                raise VideoBatchConflictError(
                    "Batch changed while local TTS was running; generated audio was not accepted."
                )
            narration = running.narration.model_copy(
                update={
                    "audio": audio,
                    "manifest": manifest,
                    "synthesized_at": utc_now(),
                }
            )
            completed = running.model_copy(
                update={
                    "status": VideoBatchStatus.PENDING_TIMELINE_REVIEW,
                    "narration": narration,
                    "remotion_props": props,
                    "input_assets": input_assets,
                    "render_input_sha256": self._render_hash(props, input_assets),
                    "narration_failure": None,
                    "updated_at": utc_now(),
                }
            )
            return await self._repository.save(completed, expected_version=running.version)

    async def submit_timeline_review(
        self,
        batch_id: UUID,
        submission: SubmitTimelineReview,
    ) -> VideoBatch:
        """Review the synthesized merged timeline without source reordering.

        Reordering source stories after their narration has been composed would
        make the review evidence lie.  The only safe path is a new batch.
        """

        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            self._require_version(batch, submission.expected_batch_version)
            if batch.status is not VideoBatchStatus.PENDING_TIMELINE_REVIEW:
                raise VideoBatchConflictError(
                    f"Timeline review is not allowed while batch is {batch.status.value}."
                )
            expected_order = [story.story_id for story in batch.stories]
            if submission.story_order is not None and submission.story_order != expected_order:
                raise VideoBatchConflictError(
                    "Merged narration fixes source order; create a replacement batch to "
                    "reorder stories."
                )
            review = TimelineReview(
                reviewer_id=submission.reviewer_id,
                decision=submission.decision,
                reviewed_batch_version=batch.version,
                story_order=expected_order,
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
            if batch.remotion_props is None:
                raise VideoBatchConflictError(
                    "A renderable batch is missing its merged Remotion props."
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
                assert running.remotion_props is not None
                artifact = await self._video_renderer.render(
                    running.batch_id,
                    running.remotion_props,
                    running.input_assets,
                )
            except asyncio.CancelledError:
                failed = running.model_copy(
                    update={
                        "status": VideoBatchStatus.FAILED,
                        "last_failure": VideoRenderFailure(
                            message="Local video rendering was interrupted."
                        ),
                        "updated_at": utc_now(),
                    }
                )
                # Persist the recoverable terminal state even while the caller
                # is being cancelled, then preserve cancellation semantics.
                await asyncio.shield(
                    self._repository.save(failed, expected_version=running.version)
                )
                raise
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
                        story.model_copy(update={"used_at": used_at}) for story in running.stories
                    ],
                    "artifact": artifact,
                    "last_failure": None,
                    "updated_at": used_at,
                }
            )
            return await self._save_render_commit(
                rendered,
                expected_version=running.version,
            )

    async def cancel(self, batch_id: UUID) -> VideoBatch:
        """Release an unrendered batch without claiming unsafe subprocess control."""

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
            if batch.status is VideoBatchStatus.PROCESSING_BATCH_TTS:
                raise VideoBatchConflictError(
                    "The active local TTS process has no safe cancellation contract; "
                    "wait for it to finish."
                )
            if batch.status is VideoBatchStatus.REJECTED:
                return batch
            cancelled = batch.model_copy(
                update={
                    "status": VideoBatchStatus.CANCELLED,
                    "narration_failure": None,
                    "last_failure": None,
                    "updated_at": utc_now(),
                }
            )
            return await self._repository.save(cancelled, expected_version=batch.version)

    async def delete(self, batch_id: UUID) -> None:
        async with self._lock_for(batch_id):
            batch = await self._repository.get(batch_id)
            if batch.status is VideoBatchStatus.PROCESSING_BATCH_TTS:
                raise VideoBatchConflictError(
                    "A batch with active local TTS cannot be deleted until synthesis completes."
                )
            await self._repository.delete(batch_id)

    async def _record_narration_failure(
        self,
        running: VideoBatch,
        exc: Exception,
    ) -> VideoBatch:
        async with self._lock_for(running.batch_id):
            current = await self._repository.get(running.batch_id)
            if (
                current.status is not VideoBatchStatus.PROCESSING_BATCH_TTS
                or current.version != running.version
            ):
                raise VideoBatchConflictError(
                    "Batch changed while local TTS was running; failure was not recorded."
                ) from exc
            failed = running.model_copy(
                update={
                    "status": VideoBatchStatus.PENDING_BATCH_TTS,
                    "narration_failure": BatchNarrationFailure(
                        message=self._failure_message(exc),
                        retryable=True,
                    ),
                    "updated_at": utc_now(),
                }
            )
            await self._repository.save(failed, expected_version=running.version)
        if isinstance(exc, GodNewsError):
            raise exc
        raise VideoNarrationSynthesisError("Local batch narration synthesis failed.") from exc

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
        for sequence, story in enumerate(stories):
            assert story.translation is not None
            assert story.script is not None
            source_manifest = await self._story_pool.production_manifest(story.story_id)
            # Validate through serialization to detach the batch's immutable
            # evidence from a mutable in-memory story object.
            script = ScriptDocument.model_validate(story.script.model_dump())
            manifest = ProductionManifest.model_validate(source_manifest.model_dump())
            result.append(
                VideoBatchStory(
                    sequence=sequence,
                    story_id=story.story_id,
                    story_version=story.version,
                    category=story.translation.screening.category,
                    title=story.title or story.source.title,
                    script=script,
                    script_sha256=model_sha256(script),
                    source_manifest=manifest,
                    source_manifest_sha256=model_sha256(manifest),
                    reserved_at=reserved_at,
                )
            )
        return result

    @staticmethod
    def _source_evidence(
        stories: Sequence[VideoBatchStory],
    ) -> builtins.list[BatchNarrationSourceEvidence]:
        return [
            BatchNarrationSourceEvidence(
                story_id=story.story_id,
                story_version=story.story_version,
                script_revision=story.script.revision,
                script_sha256=story.script_sha256,
                source_manifest_sha256=story.source_manifest_sha256,
            )
            for story in stories
        ]

    def _resolve_batch_audio_paths(self, audio: AudioBundle) -> AudioBundle:
        clips = []
        for clip in audio.clips:
            supplied = Path(clip.path).expanduser()
            path = (
                supplied.resolve()
                if supplied.is_absolute()
                else (self._audio_root / supplied).resolve()
            )
            try:
                path.relative_to(self._audio_root)
            except ValueError as exc:
                raise VideoBatchConflictError(
                    "Batch TTS returned an audio clip outside the configured output root."
                ) from exc
            if not path.is_file():
                raise VideoBatchConflictError("Batch TTS returned a missing local audio clip.")
            clips.append(clip.model_copy(update={"path": str(path)}))
        return audio.model_copy(update={"clips": clips})

    @staticmethod
    def _validate_synthesized_audio(script: ScriptDocument, audio: AudioBundle) -> None:
        script_ids = {segment.segment_id for segment in script.segments}
        clip_ids = {clip.segment_id for clip in audio.clips}
        if audio.revision != script.revision or clip_ids != script_ids:
            raise VideoBatchConflictError(
                "Batch TTS output must match the approved script revision and exact segment IDs."
            )

    @staticmethod
    def _build_merged_manifest(
        *,
        batch_id: UUID,
        script: ScriptDocument,
        audio: AudioBundle,
    ) -> ProductionManifest:
        clips = {clip.segment_id: clip for clip in audio.clips}
        cursor = 0
        timeline: builtins.list[TimelineSegment] = []
        for segment in script.segments:
            clip = clips[segment.segment_id]
            end = cursor + clip.duration_ms
            timeline.append(
                TimelineSegment(
                    segment_id=segment.segment_id,
                    sequence=segment.sequence,
                    start_ms=cursor,
                    end_ms=end,
                    text=segment.text,
                    speaker_id=segment.speaker_id,
                    emotion=segment.emotion,
                    scene_transition=segment.scene_transition,
                    visual_hint=segment.visual_hint,
                    audio_path=clip.path,
                )
            )
            cursor = end
        return ProductionManifest(
            story_id=batch_id,
            script_revision=script.revision,
            language=script.language,
            total_duration_ms=cursor,
            timeline=timeline,
        )

    @staticmethod
    def _build_remotion_props(
        *,
        batch_id: UUID,
        title: str,
        subtitle: str | None,
        manifest: ProductionManifest,
        bgm: BgmRenderSpec | None,
        host: HostVisualReservations,
    ) -> RemotionVideoProps:
        if manifest.story_id != batch_id:
            raise VideoBatchConflictError("Merged manifest must be owned by the video batch.")
        return RemotionVideoProps(
            manifest=manifest,
            title=title,
            subtitle=subtitle,
            bgm=bgm,
            visual_reservations=host,
        )

    @staticmethod
    def _validate_audio_snapshot_evidence(
        audio: AudioBundle,
        input_assets: list[VideoInputAsset],
    ) -> None:
        assets = {
            asset.local_path: asset
            for asset in input_assets
            if asset.kind is VideoInputAssetKind.AUDIO
        }
        for clip in audio.clips:
            asset = assets.get(clip.path)
            if asset is None or asset.sha256 != clip.sha256:
                raise VideoBatchConflictError(
                    "Batch TTS clip content does not match the reviewed audio snapshot."
                )

    @staticmethod
    def _snapshot_input_assets(props: RemotionVideoProps) -> list[VideoInputAsset]:
        candidates: list[tuple[VideoInputAssetKind, str]] = [
            (VideoInputAssetKind.AUDIO, segment.audio_path) for segment in props.manifest.timeline
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
                    "A reviewed video input changed; revise the batch narration or create a "
                    "replacement so the changed input receives a fresh review."
                )

    @staticmethod
    def _render_hash(props: RemotionVideoProps, assets: list[VideoInputAsset]) -> str:
        return render_input_sha256(props, assets)

    @staticmethod
    def _require_version(batch: VideoBatch, expected: int) -> None:
        if batch.version != expected:
            raise VideoBatchConflictError("Video batch changed concurrently; reload it and retry.")

    @staticmethod
    def _require_narration_review_state(
        batch: VideoBatch,
        decision: NarrationReviewDecision,
    ) -> None:
        if batch.status is VideoBatchStatus.PENDING_NARRATION_REVIEW:
            return
        if decision is NarrationReviewDecision.REVISE and batch.status in {
            VideoBatchStatus.PENDING_BATCH_TTS,
            VideoBatchStatus.PENDING_TIMELINE_REVIEW,
        }:
            return
        raise VideoBatchConflictError(
            f"Narration review is not allowed while batch is {batch.status.value}."
        )

    @staticmethod
    def _failure_message(exc: Exception) -> str:
        if isinstance(exc, GodNewsError):
            return exc.public_message
        return f"{type(exc).__name__}: local operation failed"

    async def _save_render_commit(
        self,
        batch: VideoBatch,
        *,
        expected_version: int,
    ) -> VideoBatch:
        """Finish the durable render commit before propagating task cancellation."""

        commit = asyncio.create_task(
            self._repository.save(batch, expected_version=expected_version)
        )
        try:
            return await asyncio.shield(commit)
        except asyncio.CancelledError:
            # A completed MP4 set without its DB evidence is an orphan and
            # leaves the batch stuck in RENDERING.  Finish this short commit,
            # then let the caller observe its cancellation.
            await asyncio.shield(commit)
            raise

    def _lock_for(self, batch_id: UUID) -> asyncio.Lock:
        lock = self._batch_locks.get(batch_id)
        if lock is None:
            lock = asyncio.Lock()
            self._batch_locks[batch_id] = lock
        return lock


def require_video_transition(current: VideoBatchStatus, target: VideoBatchStatus) -> None:
    if not is_video_batch_transition_allowed(current, target):
        raise VideoBatchConflictError(
            f"Video batch cannot transition from {current.value} to {target.value}."
        )
