from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from god_news.api.app import create_app
from god_news.application.source_transcriptions import SourceMediaTranscriptionService
from god_news.domain.enums import StoryStatus
from god_news.domain.models import (
    FetchedDocument,
    ScriptPreferences,
    SourceItemIngestRequest,
    Story,
)
from god_news.domain.source_media import SourceMediaArtifact, SourceVideoProbe
from god_news.domain.source_transcription import (
    ASRSegment,
    ASRTranscript,
    CaptionTranslationInput,
    ReviewSourceTranscriptionRequest,
    SourceMediaTranscriber,
    SourceMediaTranscription,
    SourceTranscriptionFailure,
    SourceTranscriptionRepository,
    SourceTranscriptionStatus,
    StartSourceTranscriptionRequest,
    TimedCaptionCue,
    TranscriptReviewDecision,
)
from god_news.errors import (
    ConcurrentSourceTranscriptionWriteError,
    SourceMediaAcquisitionError,
)
from god_news.infrastructure import source_media_asr as asr_module
from god_news.infrastructure.database import Database
from god_news.infrastructure.source_media_asr import (
    FasterWhisperSourceMediaTranscriber,
    FasterWhisperWorkerResponse,
)
from god_news.infrastructure.source_transcription_repository import (
    SqlAlchemySourceTranscriptionRepository,
)
from god_news.infrastructure.testing import InMemoryStoryRepository
from god_news.sources.models import parse_raw_source_json
from god_news.sources.registry import create_default_source_registry
from god_news.workers.faster_whisper_transcribe import _run as run_faster_whisper_worker

from .conftest import Stack

FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "reddit.json"
MEDIA_BYTES = b"verified source media"


def _story() -> Story:
    raw = parse_raw_source_json(FIXTURE.read_bytes())
    normalized = create_default_source_registry().normalize(raw)
    fetched = FetchedDocument.from_normalized_source(normalized)
    return Story(
        status=StoryStatus.FETCHED,
        source=fetched.source,
        provenance=normalized,
        original_text=fetched.content,
        target_language="zh-CN",
        preferences=ScriptPreferences(
            style="concise",
            target_duration_seconds=20,
            speaker_id="narrator",
        ),
    )


def _artifact(story: Story) -> SourceMediaArtifact:
    assert story.provenance is not None
    media = story.provenance.media[1]
    assert media.kind == "video"
    return SourceMediaArtifact(
        story_id=story.story_id,
        source=story.provenance.source,
        media_index=1,
        acquired_by="editor",
        source_url=media.url,
        canonical_story_url=story.provenance.canonical_url,
        attribution=story.provenance.attribution,
        rights=story.provenance.rights,
        publish_eligible=False,
        content_type="video/mp4",
        filename="source-1.mp4",
        sha256=hashlib.sha256(MEDIA_BYTES).hexdigest(),
        size_bytes=len(MEDIA_BYTES),
        probe=SourceVideoProbe(
            duration_ms=10_000,
            width=720,
            height=1_280,
            video_codec="h264",
            audio_codec="aac",
            fps=30,
        ),
    )


class _MediaReader:
    def __init__(self, artifact: SourceMediaArtifact, path: Path) -> None:
        self.artifact = artifact
        self.path = path

    async def media_path(
        self,
        story_id: UUID,
        artifact_id: UUID,
    ) -> tuple[SourceMediaArtifact, Path]:
        if story_id != self.artifact.story_id or artifact_id != self.artifact.artifact_id:
            raise SourceMediaAcquisitionError(story_id, "not found", status_code=404)
        return self.artifact, self.path


class _Transcriber(SourceMediaTranscriber):
    def __init__(self, *, blocking: bool = False, end_ms: int = 4_000) -> None:
        self.blocking = blocking
        self.end_ms = end_ms
        self.calls = 0
        self.started = asyncio.Event()

    @property
    def model_identity(self) -> str:
        return "test-asr:base:cpu:int8"

    async def transcribe(self, path: Path, *, language_hint: str | None) -> ASRTranscript:
        del language_hint
        assert await asyncio.to_thread(path.read_bytes) == MEDIA_BYTES
        self.calls += 1
        self.started.set()
        if self.blocking:
            await asyncio.Event().wait()
        return ASRTranscript(
            detected_language="en",
            language_probability=0.97,
            segments=[
                ASRSegment(
                    sequence=0,
                    start_ms=500,
                    end_ms=self.end_ms,
                    text="People rebuilt the local library.",
                    average_log_probability=-0.1,
                    no_speech_probability=0.01,
                )
            ],
        )


class _Translator:
    name = "test-translator"

    def __init__(self) -> None:
        self.calls = 0

    async def translate(
        self,
        *,
        transcription_id: UUID,
        source_language: str,
        target_language: str,
        cues: Sequence[CaptionTranslationInput],
    ) -> dict[UUID, str]:
        del transcription_id
        assert source_language == "en"
        assert target_language == "zh-CN"
        self.calls += 1
        return {cue.cue_id: "人们重建了当地的图书馆。" for cue in cues}


class _InMemoryRepository(SourceTranscriptionRepository):
    def __init__(self) -> None:
        self.items: dict[UUID, SourceMediaTranscription] = {}

    async def find_equivalent(
        self,
        *,
        artifact_id: UUID,
        artifact_sha256: str,
        model_identity: str,
        source_language_hint: str | None,
        target_caption_language: str,
    ) -> SourceMediaTranscription | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.artifact_id == artifact_id
                and item.artifact_sha256 == artifact_sha256
                and item.model_identity == model_identity
                and item.source_language_hint == source_language_hint
                and item.target_caption_language == target_caption_language
            ),
            None,
        )

    async def create_or_get(
        self,
        transcription: SourceMediaTranscription,
    ) -> SourceMediaTranscription:
        existing = await self.find_equivalent(
            artifact_id=transcription.artifact_id,
            artifact_sha256=transcription.artifact_sha256,
            model_identity=transcription.model_identity,
            source_language_hint=transcription.source_language_hint,
            target_caption_language=transcription.target_caption_language,
        )
        if existing is not None:
            return existing
        self.items[transcription.transcription_id] = transcription
        return transcription

    async def get(self, transcription_id: UUID) -> SourceMediaTranscription:
        return self.items[transcription_id]

    async def list_for_artifact(self, artifact_id: UUID) -> Sequence[SourceMediaTranscription]:
        return [item for item in self.items.values() if item.artifact_id == artifact_id]

    async def save(
        self,
        transcription: SourceMediaTranscription,
        *,
        expected_version: int,
    ) -> SourceMediaTranscription:
        current = self.items[transcription.transcription_id]
        if current.version != expected_version:
            raise ConcurrentSourceTranscriptionWriteError(transcription.story_id)
        self.items[transcription.transcription_id] = transcription
        return transcription

    async def recover_interrupted(self) -> int:
        recovered = 0
        for item in list(self.items.values()):
            if item.status not in {
                SourceTranscriptionStatus.QUEUED,
                SourceTranscriptionStatus.PROCESSING,
            }:
                continue
            self.items[item.transcription_id] = item.evolve(
                status=SourceTranscriptionStatus.FAILED,
                failures=[
                    *item.failures,
                    SourceTranscriptionFailure(
                        code="service_restarted",
                        message="restart",
                        retryable=True,
                    ),
                ],
                version=item.version + 1,
                updated_at=datetime.now(UTC),
            )
            recovered += 1
        return recovered


async def _service(
    tmp_path: Path,
    *,
    story: Story | None = None,
    transcriber: _Transcriber | None = None,
    max_pending: int = 2,
) -> tuple[
    SourceMediaTranscriptionService,
    SourceMediaArtifact,
    _Transcriber,
    _Translator,
]:
    story = story or _story()
    stories = InMemoryStoryRepository()
    await stories.create(story)
    path = tmp_path / "source.mp4"
    await asyncio.to_thread(path.write_bytes, MEDIA_BYTES)
    artifact = _artifact(story)
    actual_transcriber = transcriber or _Transcriber()
    translator = _Translator()
    return (
        SourceMediaTranscriptionService(
            stories=stories,
            media=_MediaReader(artifact, path),
            repository=_InMemoryRepository(),
            transcriber=actual_transcriber,
            translator=translator,
            max_pending=max_pending,
        ),
        artifact,
        actual_transcriber,
        translator,
    )


@pytest.mark.asyncio
async def test_asr_translation_review_and_idempotent_reuse(tmp_path: Path) -> None:
    story = _story()
    service, artifact, transcriber, translator = await _service(tmp_path, story=story)
    request = StartSourceTranscriptionRequest(
        expected_story_version=story.version,
        requested_by="editor",
        source_language_hint="en",
        target_caption_language="zh-CN",
    )
    try:
        queued = await service.start(story.story_id, artifact.artifact_id, request)
        pending = await service.wait(queued.transcription_id)

        assert pending.status is SourceTranscriptionStatus.PENDING_REVIEW
        assert pending.detected_language == "en"
        assert pending.language_probability == 0.97
        assert pending.attempt_count == 1
        assert pending.cues[0].captions[0].text == "People rebuilt the local library."
        assert pending.cues[0].captions[1].text == "人们重建了当地的图书馆。"
        assert transcriber.calls == 1
        assert translator.calls == 1

        revised_cue = TimedCaptionCue.model_validate(
            {
                **pending.cues[0].model_dump(),
                "captions": [
                    pending.cues[0].captions[0],
                    {
                        "language": "zh-CN",
                        "kind": "translation",
                        "text": "人们一起重建了当地的图书馆。",
                    },
                ],
            }
        )
        approved = await service.review(
            story.story_id,
            artifact.artifact_id,
            pending.transcription_id,
            ReviewSourceTranscriptionRequest(
                expected_version=pending.version,
                reviewer_id="reviewer",
                decision=TranscriptReviewDecision.APPROVE,
                revised_cues=[revised_cue],
            ),
        )
        assert approved.status is SourceTranscriptionStatus.APPROVED
        assert approved.cues[0].captions[1].text == "人们一起重建了当地的图书馆。"

        reused = await service.start(story.story_id, artifact.artifact_id, request)
        assert reused == approved
        assert transcriber.calls == 1
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_asr_cancellation_is_persisted(tmp_path: Path) -> None:
    story = _story()
    blocking = _Transcriber(blocking=True)
    service, artifact, _, _ = await _service(
        tmp_path,
        story=story,
        transcriber=blocking,
        max_pending=1,
    )
    try:
        queued = await service.start(
            story.story_id,
            artifact.artifact_id,
            StartSourceTranscriptionRequest(
                expected_story_version=story.version,
                requested_by="editor",
                target_caption_language="zh-CN",
            ),
        )
        await asyncio.wait_for(blocking.started.wait(), timeout=1)
        reused = await service.start(
            story.story_id,
            artifact.artifact_id,
            StartSourceTranscriptionRequest(
                expected_story_version=story.version,
                requested_by="another-editor",
                target_caption_language="zh-CN",
            ),
        )
        assert reused.transcription_id == queued.transcription_id
        cancelled = await service.cancel(
            story.story_id,
            artifact.artifact_id,
            queued.transcription_id,
        )
        assert cancelled.status is SourceTranscriptionStatus.CANCELLED
        assert cancelled.failures[-1].code == "operator_cancelled"
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_asr_timing_beyond_verified_video_fails_closed(tmp_path: Path) -> None:
    story = _story()
    service, artifact, _, _ = await _service(
        tmp_path,
        story=story,
        transcriber=_Transcriber(end_ms=13_000),
    )
    try:
        queued = await service.start(
            story.story_id,
            artifact.artifact_id,
            StartSourceTranscriptionRequest(
                expected_story_version=story.version,
                requested_by="editor",
                target_caption_language="zh-CN",
            ),
        )
        failed = await service.wait(queued.transcription_id)
        assert failed.status is SourceTranscriptionStatus.FAILED
        assert failed.failures[-1].code == "asr_timing_invalid"
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_sql_transcription_repository_is_idempotent_and_recovers_restart(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'asr.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemySourceTranscriptionRepository(database.sessions)
    story = _story()
    artifact = _artifact(story)
    job = SourceMediaTranscription(
        story_id=story.story_id,
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        model_identity="test-asr:base:cpu:int8",
        target_caption_language="zh-CN",
        requested_by="editor",
    )
    try:
        assert await repository.create_or_get(job) == job
        equivalent = job.model_copy(update={"transcription_id": UUID(int=123)})
        assert await repository.create_or_get(equivalent) == job
        assert await repository.recover_interrupted() == 1
        recovered = await repository.get(job.transcription_id)
        assert recovered.status is SourceTranscriptionStatus.FAILED
        assert recovered.failures[-1].code == "service_restarted"
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_source_transcription_api_runs_and_reviews_scoped_job(
    stack: Stack,
    tmp_path: Path,
) -> None:
    raw = parse_raw_source_json(FIXTURE.read_bytes())
    story = await stack.workflow.ingest_source_item(SourceItemIngestRequest(item=raw))
    path = tmp_path / "api-source.mp4"
    await asyncio.to_thread(path.write_bytes, MEDIA_BYTES)
    artifact = _artifact(story)
    service = SourceMediaTranscriptionService(
        stories=stack.repository,
        media=_MediaReader(artifact, path),
        repository=_InMemoryRepository(),
        transcriber=_Transcriber(),
        translator=_Translator(),
        max_pending=2,
    )
    stack.container.source_transcriptions = service

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                base = (
                    f"/api/v1/stories/{story.story_id}/source-media/"
                    f"{artifact.artifact_id}/transcriptions"
                )
                created = await client.post(
                    base,
                    json={
                        "expected_story_version": story.version,
                        "requested_by": "editor",
                        "source_language_hint": "en",
                        "target_caption_language": "zh-CN",
                    },
                )
                assert created.status_code == 202
                transcription_id = UUID(created.json()["transcription_id"])
                pending = await service.wait(transcription_id)

                listing = await client.get(base)
                assert listing.status_code == 200
                assert listing.json()[0]["status"] == "PENDING_REVIEW"

                scoped = f"{base}/{transcription_id}"
                fetched = await client.get(scoped)
                assert fetched.status_code == 200
                reviewed = await client.post(
                    f"{scoped}/review",
                    json={
                        "expected_version": pending.version,
                        "reviewer_id": "reviewer",
                        "decision": "approve",
                        "revised_cues": None,
                        "note": "checked against the source audio",
                    },
                )
                assert reviewed.status_code == 200
                assert reviewed.json()["status"] == "APPROVED"
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_faster_whisper_adapter_uses_bounded_supervised_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "worker-source.mp4"
    await asyncio.to_thread(path.write_bytes, MEDIA_BYTES)
    expected = ASRTranscript(
        detected_language="en",
        language_probability=0.9,
        segments=[ASRSegment(sequence=0, start_ms=0, end_ms=1_000, text="Hello")],
    )
    captured: dict[str, object] = {}

    async def fake_worker(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return FasterWhisperWorkerResponse(ok=True, transcript=expected)

    monkeypatch.setattr(asr_module, "run_json_worker", fake_worker)
    transcriber = FasterWhisperSourceMediaTranscriber(
        model="base",
        device="cpu",
        compute_type="int8",
        download_root=tmp_path / "models",
        local_files_only=True,
        timeout_seconds=30,
        max_output_bytes=4096,
        cpu_threads=2,
        beam_size=3,
        vad_filter=True,
    )

    result = await transcriber.transcribe(path, language_hint="en")

    assert result == expected
    assert transcriber.model_identity == "faster-whisper:1.2.1:base:cpu:int8"
    assert captured["timeout_seconds"] == 30
    assert captured["max_stdout_bytes"] == 4096
    request = captured["request"]
    assert isinstance(request, asr_module.FasterWhisperWorkerRequest)
    assert request.media_path == str(path.resolve())
    assert request.local_files_only is True
    assert request.language_hint == "en"


def test_faster_whisper_worker_reports_media_deleted_before_start(tmp_path: Path) -> None:
    request = asr_module.FasterWhisperWorkerRequest(
        media_path=str(tmp_path / "deleted.mp4"),
        model="base",
        device="cpu",
        compute_type="int8",
        download_root=str(tmp_path / "models"),
        local_files_only=True,
        cpu_threads=2,
        beam_size=3,
        vad_filter=True,
        language_hint=None,
    )

    response = run_faster_whisper_worker(request)

    assert response.ok is False
    assert response.error_code == "media_missing"
