from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import partial
from uuid import UUID, uuid4

from god_news.domain.models import CaptionVariant
from god_news.domain.ports import StoryRepository
from god_news.domain.source_transcription import (
    CaptionTranslationInput,
    ReviewSourceTranscriptionRequest,
    SourceMediaTranscriber,
    SourceMediaTranscriberError,
    SourceMediaTranscription,
    SourceTranscriptionFailure,
    SourceTranscriptionRepository,
    SourceTranscriptionStatus,
    StartSourceTranscriptionRequest,
    TimedCaptionCue,
    TimedCaptionTranslator,
    TranscriptReview,
    TranscriptReviewDecision,
    VerifiedSourceMediaReader,
)
from god_news.errors import (
    ConcurrentSourceTranscriptionWriteError,
    ConcurrentWriteError,
    LLMGenerationError,
    SourceTranscriptionNotFoundError,
    SourceTranscriptionOperationError,
)

logger = logging.getLogger(__name__)


class SourceMediaTranscriptionService:
    def __init__(
        self,
        *,
        stories: StoryRepository,
        media: VerifiedSourceMediaReader,
        repository: SourceTranscriptionRepository,
        transcriber: SourceMediaTranscriber | None,
        translator: TimedCaptionTranslator,
        max_pending: int,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be positive")
        self._stories = stories
        self._media = media
        self._repository = repository
        self._transcriber = transcriber
        self._translator = translator
        self._max_pending = max_pending
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._operator_cancellations: set[UUID] = set()
        self._task_lock = asyncio.Lock()
        self._closing = False

    async def start(
        self,
        story_id: UUID,
        artifact_id: UUID,
        request: StartSourceTranscriptionRequest,
    ) -> SourceMediaTranscription:
        transcriber = self._transcriber
        if transcriber is None:
            raise SourceTranscriptionOperationError(
                story_id,
                "Local source-video ASR is disabled or unavailable.",
                status_code=503,
                retryable=True,
            )
        story = await self._stories.get(story_id)
        if story.version != request.expected_story_version:
            raise ConcurrentWriteError(story_id)
        artifact, _ = await self._media.media_path(story_id, artifact_id)
        candidate = SourceMediaTranscription(
            story_id=story_id,
            artifact_id=artifact_id,
            artifact_sha256=artifact.sha256,
            model_identity=transcriber.model_identity,
            source_language_hint=request.source_language_hint,
            target_caption_language=request.target_caption_language,
            requested_by=request.requested_by,
        )
        async with self._task_lock:
            current = await self._repository.find_equivalent(
                artifact_id=artifact_id,
                artifact_sha256=artifact.sha256,
                model_identity=transcriber.model_identity,
                source_language_hint=request.source_language_hint,
                target_caption_language=request.target_caption_language,
            )
            if current is not None and current.status in {
                SourceTranscriptionStatus.QUEUED,
                SourceTranscriptionStatus.PROCESSING,
                SourceTranscriptionStatus.PENDING_REVIEW,
                SourceTranscriptionStatus.APPROVED,
            }:
                if current.status is SourceTranscriptionStatus.QUEUED:
                    if self._closing:
                        raise SourceTranscriptionOperationError(
                            story_id,
                            "The local ASR service is shutting down; retry after restart.",
                            status_code=503,
                            retryable=True,
                        )
                    if not self._task_is_active(current.transcription_id) and self._queue_is_full():
                        raise SourceTranscriptionOperationError(
                            story_id,
                            "The local ASR queue is full; retry after a current task finishes.",
                            status_code=429,
                            retryable=True,
                        )
                    self._schedule_locked(current.transcription_id)
                return current
            if self._closing or self._queue_is_full():
                message = (
                    "The local ASR service is shutting down; retry after restart."
                    if self._closing
                    else "The local ASR queue is full; retry after a current task finishes."
                )
                raise SourceTranscriptionOperationError(
                    story_id,
                    message,
                    status_code=503 if self._closing else 429,
                    retryable=True,
                )
            if current is None:
                current = await self._repository.create_or_get(candidate)
            if current.status in {
                SourceTranscriptionStatus.QUEUED,
                SourceTranscriptionStatus.PROCESSING,
                SourceTranscriptionStatus.PENDING_REVIEW,
                SourceTranscriptionStatus.APPROVED,
            }:
                if current.status is SourceTranscriptionStatus.QUEUED:
                    self._schedule_locked(current.transcription_id)
                return current
            restarted = current.evolve(
                status=SourceTranscriptionStatus.QUEUED,
                detected_language=None,
                language_probability=None,
                cues=[],
                version=current.version + 1,
                updated_at=datetime.now(UTC),
            )
            restarted = await self._repository.save(
                restarted,
                expected_version=current.version,
            )
            self._schedule_locked(restarted.transcription_id)
            return restarted

    async def get(
        self,
        story_id: UUID,
        artifact_id: UUID,
        transcription_id: UUID,
    ) -> SourceMediaTranscription:
        return await self._scoped(story_id, artifact_id, transcription_id)

    async def list(
        self,
        story_id: UUID,
        artifact_id: UUID,
    ) -> Sequence[SourceMediaTranscription]:
        await self._media.media_path(story_id, artifact_id)
        return await self._repository.list_for_artifact(artifact_id)

    async def wait(self, transcription_id: UUID) -> SourceMediaTranscription:
        async with self._task_lock:
            task = self._tasks.get(transcription_id)
        if task is not None:
            await asyncio.shield(task)
        return await self._repository.get(transcription_id)

    async def review(
        self,
        story_id: UUID,
        artifact_id: UUID,
        transcription_id: UUID,
        request: ReviewSourceTranscriptionRequest,
    ) -> SourceMediaTranscription:
        current = await self._scoped(story_id, artifact_id, transcription_id)
        if current.version != request.expected_version:
            raise ConcurrentSourceTranscriptionWriteError(current.story_id)
        if current.status is not SourceTranscriptionStatus.PENDING_REVIEW:
            raise SourceTranscriptionOperationError(
                current.story_id,
                "Only a pending source transcript can be reviewed.",
            )
        cues = request.revised_cues or current.cues
        if request.revised_cues is not None:
            before = [
                (cue.cue_id, cue.sequence, cue.start_ms, cue.end_ms) for cue in current.cues
            ]
            after = [(cue.cue_id, cue.sequence, cue.start_ms, cue.end_ms) for cue in cues]
            if before != after:
                raise SourceTranscriptionOperationError(
                    current.story_id,
                    "Transcript review may edit caption text but cannot rewrite timing evidence.",
                )
        review = TranscriptReview(
            reviewer_id=request.reviewer_id,
            decision=request.decision,
            reviewed_version=current.version,
            note=request.note,
        )
        status = (
            SourceTranscriptionStatus.APPROVED
            if request.decision is TranscriptReviewDecision.APPROVE
            else SourceTranscriptionStatus.REJECTED
        )
        revised = current.evolve(
            status=status,
            cues=cues,
            reviews=[*current.reviews, review],
            version=current.version + 1,
            updated_at=datetime.now(UTC),
        )
        return await self._repository.save(revised, expected_version=current.version)

    async def cancel(
        self,
        story_id: UUID,
        artifact_id: UUID,
        transcription_id: UUID,
    ) -> SourceMediaTranscription:
        await self._scoped(story_id, artifact_id, transcription_id)
        async with self._task_lock:
            task = self._tasks.get(transcription_id)
            if task is not None and not task.done():
                self._operator_cancellations.add(transcription_id)
                task.cancel()
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
        current = await self._repository.get(transcription_id)
        if current.status in {
            SourceTranscriptionStatus.PENDING_REVIEW,
            SourceTranscriptionStatus.APPROVED,
            SourceTranscriptionStatus.REJECTED,
            SourceTranscriptionStatus.FAILED,
            SourceTranscriptionStatus.CANCELLED,
        }:
            return current
        await self._mark_terminal(
            transcription_id,
            status=SourceTranscriptionStatus.CANCELLED,
            failure=SourceTranscriptionFailure(
                code="operator_cancelled",
                message="The source transcription was cancelled by an operator.",
                retryable=True,
            ),
        )
        return await self._repository.get(transcription_id)

    async def recover_interrupted(self) -> int:
        return await self._repository.recover_interrupted()

    async def aclose(self) -> None:
        async with self._task_lock:
            self._closing = True
            tasks = tuple(self._tasks.values())
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._task_lock:
            self._tasks.clear()

    def _schedule_locked(self, transcription_id: UUID) -> None:
        existing = self._tasks.get(transcription_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._execute(transcription_id),
            name=f"god-news-source-asr-{transcription_id}",
        )
        self._tasks[transcription_id] = task
        task.add_done_callback(partial(self._task_finished, transcription_id))

    def _queue_is_full(self) -> bool:
        return sum(not task.done() for task in self._tasks.values()) >= self._max_pending

    def _task_is_active(self, transcription_id: UUID) -> bool:
        task = self._tasks.get(transcription_id)
        return task is not None and not task.done()

    async def _scoped(
        self,
        story_id: UUID,
        artifact_id: UUID,
        transcription_id: UUID,
    ) -> SourceMediaTranscription:
        item = await self._repository.get(transcription_id)
        if item.story_id != story_id or item.artifact_id != artifact_id:
            raise SourceTranscriptionNotFoundError(transcription_id)
        return item

    def _task_finished(self, transcription_id: UUID, task: asyncio.Task[None]) -> None:
        self._tasks.pop(transcription_id, None)
        self._operator_cancellations.discard(transcription_id)
        error = None if task.cancelled() else task.exception()
        if error is not None:
            logger.error(
                "source transcription task escaped supervision transcription_id=%s error_type=%s",
                transcription_id,
                type(error).__name__,
            )

    async def _execute(self, transcription_id: UUID) -> None:
        try:
            await self._execute_work(transcription_id)
        except asyncio.CancelledError:
            operator = transcription_id in self._operator_cancellations
            await self._mark_terminal(
                transcription_id,
                status=SourceTranscriptionStatus.CANCELLED,
                failure=SourceTranscriptionFailure(
                    code="operator_cancelled" if operator else "service_shutdown",
                    message=(
                        "The source transcription was cancelled by an operator."
                        if operator
                        else "The source transcription stopped during service shutdown."
                    ),
                    retryable=True,
                ),
            )
            raise
        except SourceMediaTranscriberError as exc:
            await self._mark_terminal(
                transcription_id,
                status=SourceTranscriptionStatus.FAILED,
                failure=SourceTranscriptionFailure(
                    code=exc.code,
                    message=str(exc),
                    retryable=exc.retryable,
                ),
            )
        except LLMGenerationError as exc:
            await self._mark_terminal(
                transcription_id,
                status=SourceTranscriptionStatus.FAILED,
                failure=SourceTranscriptionFailure(
                    code="caption_translation_failed",
                    message=exc.public_message,
                    retryable=exc.retryable,
                ),
            )
        except Exception:
            logger.exception(
                "source transcription failed transcription_id=%s",
                transcription_id,
            )
            await self._mark_terminal(
                transcription_id,
                status=SourceTranscriptionStatus.FAILED,
                failure=SourceTranscriptionFailure(
                    code="source_transcription_internal_error",
                    message="Source transcription failed unexpectedly; inspect trace-linked logs.",
                    retryable=False,
                ),
            )

    async def _execute_work(self, transcription_id: UUID) -> None:
        queued = await self._repository.get(transcription_id)
        transcriber = self._transcriber
        if transcriber is None:
            raise SourceMediaTranscriberError(
                "asr_unavailable",
                "Local ASR became unavailable before the queued task started.",
                retryable=True,
            )
        processing = queued.evolve(
            status=SourceTranscriptionStatus.PROCESSING,
            attempt_count=queued.attempt_count + 1,
            version=queued.version + 1,
            updated_at=datetime.now(UTC),
        )
        processing = await self._repository.save(processing, expected_version=queued.version)
        artifact, path = await self._media.media_path(
            processing.story_id,
            processing.artifact_id,
        )
        if artifact.sha256 != processing.artifact_sha256:
            raise SourceMediaTranscriberError(
                "source_media_changed",
                "Source media no longer matches the approved transcription input snapshot.",
                retryable=False,
            )
        transcript = await transcriber.transcribe(
            path,
            language_hint=processing.source_language_hint,
        )
        if transcript.segments[-1].end_ms > artifact.probe.duration_ms + 2_000:
            raise SourceMediaTranscriberError(
                "asr_timing_invalid",
                "ASR timing extends beyond the verified source-video duration.",
                retryable=False,
            )
        cue_ids = [uuid4() for _ in transcript.segments]
        translations: dict[UUID, str] = {}
        if transcript.detected_language.casefold() != processing.target_caption_language.casefold():
            translations = await self._translator.translate(
                transcription_id=processing.transcription_id,
                source_language=transcript.detected_language,
                target_language=processing.target_caption_language,
                cues=[
                    CaptionTranslationInput(cue_id=cue_id, text=segment.text)
                    for cue_id, segment in zip(cue_ids, transcript.segments, strict=True)
                ],
            )
            if set(translations) != set(cue_ids):
                raise LLMGenerationError(
                    "Caption translator did not return every timed cue.",
                    processing.transcription_id,
                    retryable=False,
                )
        cues = []
        for cue_id, segment in zip(cue_ids, transcript.segments, strict=True):
            captions = [
                CaptionVariant(
                    language=transcript.detected_language,
                    kind="verbatim",
                    text=segment.text,
                )
            ]
            if translations:
                captions.append(
                    CaptionVariant(
                        language=processing.target_caption_language,
                        kind="translation",
                        text=translations[cue_id],
                    )
                )
            cues.append(
                TimedCaptionCue(
                    cue_id=cue_id,
                    sequence=segment.sequence,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    captions=captions,
                    average_log_probability=segment.average_log_probability,
                    no_speech_probability=segment.no_speech_probability,
                )
            )
        completed = processing.evolve(
            status=SourceTranscriptionStatus.PENDING_REVIEW,
            detected_language=transcript.detected_language,
            language_probability=transcript.language_probability,
            cues=cues,
            version=processing.version + 1,
            updated_at=datetime.now(UTC),
        )
        await self._repository.save(completed, expected_version=processing.version)

    async def _mark_terminal(
        self,
        transcription_id: UUID,
        *,
        status: SourceTranscriptionStatus,
        failure: SourceTranscriptionFailure,
    ) -> None:
        for _ in range(2):
            current = await self._repository.get(transcription_id)
            if current.status in {
                SourceTranscriptionStatus.PENDING_REVIEW,
                SourceTranscriptionStatus.APPROVED,
                SourceTranscriptionStatus.REJECTED,
                SourceTranscriptionStatus.FAILED,
                SourceTranscriptionStatus.CANCELLED,
            }:
                return
            failed = current.evolve(
                status=status,
                failures=[*current.failures, failure],
                version=current.version + 1,
                updated_at=datetime.now(UTC),
            )
            try:
                await self._repository.save(failed, expected_version=current.version)
                return
            except ConcurrentSourceTranscriptionWriteError:
                continue
        logger.error(
            "source transcription terminal state lost concurrent-write race "
            "transcription_id=%s intended_status=%s",
            transcription_id,
            status.value,
        )
