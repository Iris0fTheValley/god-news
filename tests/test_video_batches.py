from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from anyio import Path as AsyncPath
from pydantic import ValidationError
from sqlalchemy import text

from god_news.api.app import create_app
from god_news.application.video_batches import VideoBatchService
from god_news.domain.enums import ContentCategory, ReviewDecision
from god_news.domain.models import (
    FirstReviewSubmission,
    IngestRequest,
    ScriptReviewSubmission,
    SecondReviewSubmission,
    SynthesizeStoryRequest,
    TextSource,
)
from god_news.domain.video import (
    BgmSelection,
    CreateVideoBatch,
    LegacyVideoRenderArtifact,
    NarrationReviewDecision,
    SubmitNarrationReview,
    SubmitTimelineReview,
    SynthesizeBatchNarration,
    TimelineReviewDecision,
    VideoBatch,
    VideoBatchStatus,
)
from god_news.errors import TTSGenerationError
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.infrastructure.video_assets import LocalBgmCatalog
from god_news.infrastructure.video_host import PlaceholderHostRenderer
from god_news.infrastructure.video_repository import SqlAlchemyVideoBatchRepository
from god_news.infrastructure.video_testing import (
    DeterministicBatchNarrationComposer,
    DeterministicBatchVideoRenderer,
    InMemoryVideoBatchRepository,
)
from god_news.video_errors import (
    BgmTrackNotFoundError,
    VideoBatchConflictError,
    VideoRenderingError,
    VideoStoryUnavailableError,
)

from .conftest import Stack


async def _done_story(stack: Stack, text: str):  # type: ignore[no-untyped-def]
    story = await stack.workflow.ingest(
        IngestRequest(
            source=TextSource(text=text, title=text[:40], language="en"),
        ),
        trace_id=uuid4(),
    )
    script_ready = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="first-editor",
        ),
    )
    pending_tts = await stack.workflow.submit_script_review(
        script_ready.story_id,
        ScriptReviewSubmission(
            expected_story_version=script_ready.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="script-editor",
        ),
    )
    pending_second_review = await stack.workflow.synthesize(
        pending_tts.story_id,
        SynthesizeStoryRequest(expected_story_version=pending_tts.version),
    )
    return await stack.workflow.submit_second_review(
        pending_second_review.story_id,
        SecondReviewSubmission(
            expected_story_version=pending_second_review.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="final-editor",
        ),
    )


def _service(
    stack: Stack,
    tmp_path: Path,
) -> tuple[
    VideoBatchService,
    InMemoryVideoBatchRepository,
    DeterministicBatchNarrationComposer,
    DeterministicBatchVideoRenderer,
]:
    repository = InMemoryVideoBatchRepository()
    composer = DeterministicBatchNarrationComposer()
    renderer = DeterministicBatchVideoRenderer(tmp_path / "videos")
    service = VideoBatchService(
        story_pool=stack.workflow,
        repository=repository,
        host_renderer=PlaceholderHostRenderer(),
        narration_composer=composer,
        synthesizer=stack.synthesizer,
        video_renderer=renderer,
        bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
        audio_root=stack.settings.output_dir,
    )
    return service, repository, composer, renderer


async def _approve_and_synthesize(
    service: VideoBatchService,
    batch_id: UUID,
    version: int,
) -> VideoBatch:
    approved = await service.submit_narration_review(
        batch_id,
        SubmitNarrationReview(
            expected_batch_version=version,
            decision=NarrationReviewDecision.APPROVE,
            reviewer_id="narration-editor",
        ),
    )
    return await service.synthesize_narration(
        batch_id,
        SynthesizeBatchNarration(expected_batch_version=approved.version),
    )


@pytest.mark.asyncio
async def test_batch_keeps_source_snapshots_but_exposes_no_render_plan_before_batch_tts(
    stack: Stack,
    tmp_path: Path,
) -> None:
    kindness = await _done_story(stack, "A neighbor quietly helped carry groceries home.")
    forum = await _done_story(stack, "A Reddit forum thanked volunteers after the storm.")
    service, repository, composer, _ = _service(stack, tmp_path)

    batch = await service.create(
        CreateVideoBatch(
            title="Daily kindness",
            story_ids=[forum.story_id, kindness.story_id],
            max_stories=2,
        )
    )

    assert batch.status is VideoBatchStatus.PENDING_NARRATION_REVIEW
    assert composer.calls == 1
    assert [story.category for story in batch.stories] == [
        ContentCategory.KINDNESS,
        ContentCategory.FORUM,
    ]
    assert batch.remotion_props is None
    assert batch.input_assets == []
    assert batch.render_input_sha256 is None
    assert await repository.protected_asset_paths() == []
    assert [item.story_id for item in batch.narration.source_evidence] == [
        story.story_id for story in batch.stories
    ]
    assert all(
        item.script_sha256 == story.script_sha256
        for item, story in zip(batch.narration.source_evidence, batch.stories, strict=True)
    )
    source_segment_ids = {
        segment.segment_id for story in batch.stories for segment in story.script.segments
    }
    assert source_segment_ids.isdisjoint(
        {segment.segment_id for segment in batch.narration.script.segments}
    )

    with pytest.raises(VideoBatchConflictError):
        await service.synthesize_narration(
            batch.batch_id,
            SynthesizeBatchNarration(expected_batch_version=batch.version),
        )
    with pytest.raises(VideoBatchConflictError):
        await service.render(batch.batch_id, expected_version=batch.version)


@pytest.mark.asyncio
async def test_merged_audio_is_the_only_remotion_input_and_timeline_cannot_reorder(
    stack: Stack,
    tmp_path: Path,
) -> None:
    first = await _done_story(stack, "A neighbor repaired a wheelchair ramp overnight.")
    second = await _done_story(stack, "A short video clip records a careful rescue.")
    service, repository, _, renderer = _service(stack, tmp_path)
    batch = await service.create(
        CreateVideoBatch(
            title="Merged cut", story_ids=[second.story_id, first.story_id], max_stories=2
        )
    )

    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    assert synthesized.status is VideoBatchStatus.PENDING_TIMELINE_REVIEW
    assert synthesized.narration.audio is not None
    assert synthesized.narration.manifest is not None
    assert synthesized.remotion_props is not None
    assert synthesized.remotion_props.manifest == synthesized.narration.manifest
    assert synthesized.remotion_props.manifest.story_id == synthesized.batch_id
    assert {segment.segment_id for segment in synthesized.remotion_props.manifest.timeline} == {
        segment.segment_id for segment in synthesized.narration.script.segments
    }
    assert [
        segment.scene_transition for segment in synthesized.remotion_props.manifest.timeline
    ] == [segment.scene_transition for segment in synthesized.narration.script.segments]
    assert {
        asset.local_path for asset in synthesized.input_assets if asset.kind.value == "audio"
    } == {segment.audio_path for segment in synthesized.remotion_props.manifest.timeline}
    assert not {
        segment.audio_path
        for story in synthesized.stories
        for segment in story.source_manifest.timeline
    } & {asset.local_path for asset in synthesized.input_assets if asset.kind.value == "audio"}
    assert set(await repository.protected_asset_paths()) == {
        Path(asset.local_path) for asset in synthesized.input_assets
    }

    with pytest.raises(VideoBatchConflictError, match="fixes source order"):
        await service.submit_timeline_review(
            synthesized.batch_id,
            SubmitTimelineReview(
                expected_batch_version=synthesized.version,
                decision=TimelineReviewDecision.APPROVE,
                reviewer_id="timeline-editor",
                story_order=list(reversed([story.story_id for story in synthesized.stories])),
            ),
        )

    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
            story_order=[story.story_id for story in synthesized.stories],
        ),
    )
    assert approved.status is VideoBatchStatus.READY_TO_RENDER
    rendered = await service.render(approved.batch_id, expected_version=approved.version)
    assert rendered.status is VideoBatchStatus.RENDERED
    assert renderer.calls == 1
    assert rendered.artifact is not None
    assert all(story.used_at == rendered.artifact.rendered_at for story in rendered.stories)


@pytest.mark.asyncio
async def test_narration_revision_clears_only_derived_batch_media_and_reenters_review(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "Volunteers repaired a playground before school opened.")
    service, repository, _, _ = _service(stack, tmp_path)
    batch = await service.create(CreateVideoBatch(title="Revision cut", story_ids=[story.story_id]))
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)

    first_segment = synthesized.narration.script.segments[0].model_copy(
        update={"text": "Revised bridge: volunteers repaired the playground before school."}
    )
    revised_script = synthesized.narration.script.model_copy(update={"segments": [first_segment]})
    revised = await service.submit_narration_review(
        synthesized.batch_id,
        SubmitNarrationReview(
            expected_batch_version=synthesized.version,
            decision=NarrationReviewDecision.REVISE,
            reviewer_id="narration-editor",
            revised_script=revised_script,
        ),
    )

    assert revised.status is VideoBatchStatus.PENDING_NARRATION_REVIEW
    assert revised.narration.script.revision == synthesized.narration.script.revision + 1
    assert revised.narration.audio is None
    assert revised.narration.manifest is None
    assert revised.remotion_props is None
    assert revised.input_assets == []
    assert revised.render_input_sha256 is None
    assert revised.timeline_review is None
    assert revised.narration.source_evidence == synthesized.narration.source_evidence
    assert await repository.protected_asset_paths() == []


@pytest.mark.asyncio
async def test_batch_tts_failure_records_retryable_evidence_without_fake_manifest(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A baker shared breakfast with stranded commuters.")
    service, _, _, _ = _service(stack, tmp_path)
    batch = await service.create(
        CreateVideoBatch(title="Retry narration", story_ids=[story.story_id])
    )
    approved = await service.submit_narration_review(
        batch.batch_id,
        SubmitNarrationReview(
            expected_batch_version=batch.version,
            decision=NarrationReviewDecision.APPROVE,
            reviewer_id="narration-editor",
        ),
    )
    stack.synthesizer.fail_next = True

    with pytest.raises(TTSGenerationError):
        await service.synthesize_narration(
            approved.batch_id,
            SynthesizeBatchNarration(expected_batch_version=approved.version),
        )

    failed = await service.get(approved.batch_id)
    assert failed.status is VideoBatchStatus.PENDING_BATCH_TTS
    assert failed.narration_failure is not None
    assert failed.narration.audio is None
    assert failed.narration.manifest is None
    assert failed.remotion_props is None
    assert failed.input_assets == []
    assert failed.render_input_sha256 is None


@pytest.mark.asyncio
async def test_timeline_rejection_and_cancel_release_story_claims(
    stack: Stack,
    tmp_path: Path,
) -> None:
    rejected_story = await _done_story(
        stack, "A nurse organized free checkups for elderly neighbors."
    )
    cancelled_story = await _done_story(stack, "A dog waited beside a lost child until help came.")
    service, _, _, _ = _service(stack, tmp_path)

    rejected_batch = await service.create(
        CreateVideoBatch(title="Rejected cut", story_ids=[rejected_story.story_id])
    )
    synthesized = await _approve_and_synthesize(
        service, rejected_batch.batch_id, rejected_batch.version
    )
    rejected = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.REJECT,
            reviewer_id="timeline-editor",
            note="Needs different source selection.",
        ),
    )
    assert rejected.status is VideoBatchStatus.REJECTED
    replacement = await service.create(
        CreateVideoBatch(title="Replacement", story_ids=[rejected_story.story_id])
    )
    assert replacement.status is VideoBatchStatus.PENDING_NARRATION_REVIEW

    pending = await service.create(
        CreateVideoBatch(title="Cancelled cut", story_ids=[cancelled_story.story_id])
    )
    cancelled = await service.cancel(pending.batch_id)
    assert cancelled.status is VideoBatchStatus.CANCELLED
    second_replacement = await service.create(
        CreateVideoBatch(title="Replacement 2", story_ids=[cancelled_story.story_id])
    )
    assert second_replacement.status is VideoBatchStatus.PENDING_NARRATION_REVIEW


@pytest.mark.asyncio
async def test_failed_render_keeps_claim_and_can_retry(stack: Stack, tmp_path: Path) -> None:
    story = await _done_story(stack, "A community fixed a library roof before the rain arrived.")
    service, _, _, renderer = _service(stack, tmp_path)
    batch = await service.create(CreateVideoBatch(title="Retry render", story_ids=[story.story_id]))
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
        ),
    )
    renderer.fail_next = True
    with pytest.raises(VideoRenderingError):
        await service.render(approved.batch_id, expected_version=approved.version)

    failed = await service.get(approved.batch_id)
    assert failed.status is VideoBatchStatus.FAILED
    assert failed.last_failure is not None
    with pytest.raises(VideoStoryUnavailableError):
        await service.create(CreateVideoBatch(title="Still claimed", story_ids=[story.story_id]))
    rendered = await service.render(failed.batch_id, expected_version=failed.version)
    assert rendered.status is VideoBatchStatus.RENDERED
    assert renderer.calls == 2


@pytest.mark.asyncio
async def test_render_cancellation_persists_retryable_failed_state(
    stack: Stack,
    tmp_path: Path,
) -> None:
    class BlockingRenderer:
        name = "blocking-test-renderer"

        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def render(self, batch_id, props, input_assets):  # type: ignore[no-untyped-def]
            del batch_id, props, input_assets
            self.started.set()
            await asyncio.Future()

    story = await _done_story(stack, "A town restored a footbridge before school reopened.")
    repository = InMemoryVideoBatchRepository()
    renderer = BlockingRenderer()
    service = VideoBatchService(
        story_pool=stack.workflow,
        repository=repository,
        host_renderer=PlaceholderHostRenderer(),
        narration_composer=DeterministicBatchNarrationComposer(),
        synthesizer=stack.synthesizer,
        video_renderer=renderer,
        bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
        audio_root=stack.settings.output_dir,
    )
    batch = await service.create(
        CreateVideoBatch(title="Interrupted render", story_ids=[story.story_id])
    )
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
        ),
    )

    task = asyncio.create_task(
        service.render(approved.batch_id, expected_version=approved.version)
    )
    await renderer.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    failed = await service.get(approved.batch_id)
    assert failed.status is VideoBatchStatus.FAILED
    assert failed.last_failure is not None
    assert failed.last_failure.retryable is True


@pytest.mark.asyncio
async def test_render_commit_finishes_before_cancellation_propagates(
    stack: Stack,
    tmp_path: Path,
) -> None:
    class BlockingCommitRepository(InMemoryVideoBatchRepository):
        def __init__(self) -> None:
            super().__init__()
            self.commit_started = asyncio.Event()
            self.release_commit = asyncio.Event()

        async def save(self, batch, *, expected_version):  # type: ignore[no-untyped-def]
            if batch.status is VideoBatchStatus.RENDERED:
                self.commit_started.set()
                await self.release_commit.wait()
            return await super().save(batch, expected_version=expected_version)

    story = await _done_story(stack, "Volunteers reopened a weather-damaged reading room.")
    repository = BlockingCommitRepository()
    service = VideoBatchService(
        story_pool=stack.workflow,
        repository=repository,
        host_renderer=PlaceholderHostRenderer(),
        narration_composer=DeterministicBatchNarrationComposer(),
        synthesizer=stack.synthesizer,
        video_renderer=DeterministicBatchVideoRenderer(tmp_path / "videos"),
        bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
        audio_root=stack.settings.output_dir,
    )
    batch = await service.create(
        CreateVideoBatch(title="Durable commit", story_ids=[story.story_id])
    )
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
        ),
    )

    task = asyncio.create_task(
        service.render(approved.batch_id, expected_version=approved.version)
    )
    await repository.commit_started.wait()
    task.cancel()
    repository.release_commit.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (await service.get(approved.batch_id)).status is VideoBatchStatus.RENDERED


@pytest.mark.asyncio
async def test_startup_recovery_turns_orphaned_render_into_retryable_failure(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "Neighbors rebuilt a storm-damaged community noticeboard.")
    service, repository, _, _ = _service(stack, tmp_path)
    batch = await service.create(
        CreateVideoBatch(title="Crash recovery", story_ids=[story.story_id])
    )
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
        ),
    )
    orphaned = approved.model_copy(
        update={
            "status": VideoBatchStatus.RENDERING,
            "version": approved.version + 1,
        }
    )
    repository._batches[approved.batch_id] = orphaned

    assert await service.recover_interrupted() == 1
    recovered = await service.get(approved.batch_id)
    assert recovered.status is VideoBatchStatus.FAILED
    assert recovered.last_failure is not None
    assert recovered.last_failure.retryable is True


@pytest.mark.asyncio
async def test_render_rejects_mutated_merged_input_after_timeline_approval(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A neighbor repaired a wheelchair ramp overnight.")
    bgm_dir = tmp_path / "bgm"
    bgm_dir.mkdir()
    track_path = bgm_dir / "calm.mp3"
    track_path.write_bytes(b"approved-bgm")
    service, _, _, renderer = _service(stack, tmp_path)
    track = (await service.list_bgm())[0]
    batch = await service.create(
        CreateVideoBatch(
            title="Immutable input", story_ids=[story.story_id], bgm_track_id=track.track_id
        )
    )
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    approved = await service.submit_timeline_review(
        synthesized.batch_id,
        SubmitTimelineReview(
            expected_batch_version=synthesized.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
        ),
    )
    track_path.write_bytes(b"mutated-after-review")

    with pytest.raises(VideoBatchConflictError, match="input changed"):
        await service.render(approved.batch_id, expected_version=approved.version)
    assert renderer.calls == 0
    assert (await service.get(approved.batch_id)).status is VideoBatchStatus.READY_TO_RENDER


@pytest.mark.asyncio
async def test_sql_repository_persists_merged_narration_and_used_at_atomically(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A family opened a free pantry on their block.")
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'video.db').as_posix()}")
    await database.create_schema()
    try:
        await SqlAlchemyStoryRepository(database.sessions).create(story)
        repository = SqlAlchemyVideoBatchRepository(database.sessions)
        renderer = DeterministicBatchVideoRenderer(tmp_path / "sql-videos")
        service = VideoBatchService(
            story_pool=stack.workflow,
            repository=repository,
            host_renderer=PlaceholderHostRenderer(),
            narration_composer=DeterministicBatchNarrationComposer(),
            synthesizer=stack.synthesizer,
            video_renderer=renderer,
            bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
            audio_root=stack.settings.output_dir,
        )
        batch = await service.create(
            CreateVideoBatch(title="Persistent cut", story_ids=[story.story_id])
        )
        synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
        approved = await service.submit_timeline_review(
            synthesized.batch_id,
            SubmitTimelineReview(
                expected_batch_version=synthesized.version,
                decision=TimelineReviewDecision.APPROVE,
                reviewer_id="timeline-editor",
            ),
        )
        orphaned = VideoBatch.model_validate(
            approved.model_copy(
                update={
                    "status": VideoBatchStatus.RENDERING,
                    "version": approved.version + 1,
                }
            ).model_dump()
        )
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE video_batches SET status = :status, batch_json = :batch_json, "
                    "version = :version WHERE batch_id = :batch_id"
                ),
                {
                    "status": orphaned.status.value,
                    "batch_json": orphaned.model_dump_json(),
                    "version": orphaned.version,
                    "batch_id": str(orphaned.batch_id),
                },
            )
        assert await repository.recover_interrupted_rendering() == [orphaned.batch_id]
        recovered = await repository.get(orphaned.batch_id)
        assert recovered.status is VideoBatchStatus.FAILED
        assert recovered.last_failure is not None
        rendered = await service.render(recovered.batch_id, expected_version=recovered.version)

        reloaded = await repository.get(rendered.batch_id)
        assert reloaded.status is VideoBatchStatus.RENDERED
        assert reloaded.narration.manifest == rendered.narration.manifest
        assert reloaded.stories[0].used_at == rendered.stories[0].used_at
        assert await repository.unavailable_story_ids([story.story_id]) == {story.story_id}

        assert rendered.artifact is not None
        current_output = rendered.artifact.outputs[0]
        legacy_payload = rendered.model_dump(mode="json")
        legacy_payload["artifact"] = {
            "local_path": current_output.local_path,
            "size_bytes": current_output.size_bytes,
            "sha256": current_output.sha256,
            "renderer": rendered.artifact.renderer,
            "rendered_at": rendered.artifact.rendered_at.isoformat(),
        }
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE video_batches SET batch_json = :batch_json "
                    "WHERE batch_id = :batch_id"
                ),
                {
                    "batch_json": json.dumps(legacy_payload),
                    "batch_id": str(rendered.batch_id),
                },
            )

        legacy = await repository.get(rendered.batch_id)
        assert isinstance(legacy.artifact, LegacyVideoRenderArtifact)
        stack.container.video_batches = service

        async def factory(settings):  # type: ignore[no-untyped-def]
            del settings
            return stack.container

        app = create_app(stack.settings, container_factory=factory)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                detail = await client.get(f"/api/v1/video/batches/{rendered.batch_id}")
                assert detail.status_code == 200
                assert detail.json()["artifact"]["renderer"] == rendered.artifact.renderer
                assert "local_path" not in detail.json()["artifact"]
                listing = await client.get("/api/v1/video/batches")
                assert listing.status_code == 200
                assert any(
                    item["batch_id"] == str(rendered.batch_id)
                    and "local_path" not in item["artifact"]
                    for item in listing.json()
                )
                legacy_output = await client.get(
                    f"/api/v1/video/batches/{rendered.batch_id}/outputs/douyin_vertical"
                )
                assert legacy_output.status_code == 409
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_sql_repository_reports_legacy_batch_payload_without_fabricating_narration(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'legacy-video.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyVideoBatchRepository(database.sessions)
    batch_id = uuid4()
    try:
        now = datetime.now(UTC)
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO video_batches "
                    "(batch_id, status, batch_json, version, created_at, updated_at) "
                    "VALUES (:batch_id, :status, :batch_json, :version, :created_at, :updated_at)"
                ),
                {
                    "batch_id": str(batch_id),
                    "status": "PENDING_TIMELINE_REVIEW",
                    "batch_json": '{"legacy_flattened_render_plan":true}',
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        with pytest.raises(VideoBatchConflictError, match="current narration-review schema"):
            await repository.get(batch_id)
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_video_api_exposes_narration_review_manual_tts_and_timeline_gate(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A teacher organized rides home during a storm.")
    service, _, _, _ = _service(stack, tmp_path)
    stack.container.video_batches = service
    stack.settings.video_render_output_dir = tmp_path / "videos"

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created_response = await client.post(
                "/api/v1/video/batches",
                json={"title": "API cut", "story_ids": [str(story.story_id)], "max_stories": 1},
            )
            assert created_response.status_code == 201
            created = created_response.json()
            assert created["status"] == "PENDING_NARRATION_REVIEW"
            assert created["remotion_props"] is None

            premature_preview = await client.get(
                f"/api/v1/video/batches/{created['batch_id']}/audio/{uuid4()}"
            )
            assert premature_preview.status_code == 409

            blocked = await client.post(
                f"/api/v1/video/batches/{created['batch_id']}/narration/synthesize",
                json={"expected_batch_version": created["version"]},
            )
            assert blocked.status_code == 409

            narration_review = await client.post(
                f"/api/v1/video/batches/{created['batch_id']}/narration-review",
                json={
                    "expected_batch_version": created["version"],
                    "decision": "approve",
                    "reviewer_id": "narration-editor",
                },
            )
            assert narration_review.status_code == 200
            approved_narration = narration_review.json()
            assert approved_narration["status"] == "PENDING_BATCH_TTS"

            synthesized_response = await client.post(
                f"/api/v1/video/batches/{created['batch_id']}/narration/synthesize",
                json={"expected_batch_version": approved_narration["version"]},
            )
            assert synthesized_response.status_code == 200
            synthesized = synthesized_response.json()
            assert synthesized["status"] == "PENDING_TIMELINE_REVIEW"
            clip = synthesized["narration"]["audio"]["clips"][0]

            preview = await client.get(
                f"/api/v1/video/batches/{created['batch_id']}/audio/{clip['segment_id']}"
            )
            assert preview.status_code == 200
            assert preview.headers["content-type"].startswith("audio/wav")
            assert preview.content.startswith(b"RIFF")

            timeline = await client.post(
                f"/api/v1/video/batches/{created['batch_id']}/timeline-review",
                json={
                    "expected_batch_version": synthesized["version"],
                    "decision": "approve",
                    "reviewer_id": "timeline-editor",
                    "story_order": [str(story.story_id)],
                },
            )
            assert timeline.status_code == 200
            ready = timeline.json()
            assert ready["status"] == "READY_TO_RENDER"

            rendered_response = await client.post(
                f"/api/v1/video/batches/{created['batch_id']}/render",
                json={"expected_batch_version": ready["version"]},
            )
            assert rendered_response.status_code == 200
            rendered = rendered_response.json()
            assert rendered["status"] == "RENDERED"
            assert {output["profile_id"] for output in rendered["artifact"]["outputs"]} == {
                "douyin_vertical",
                "bilibili_horizontal",
            }
            assert all("local_path" not in output for output in rendered["artifact"]["outputs"])
            resolved_tmp = await asyncio.to_thread(tmp_path.resolve)
            resolved_output = await asyncio.to_thread(stack.settings.output_dir.resolve)
            assert str(resolved_tmp) not in json.dumps(rendered)
            assert str(resolved_output) not in json.dumps(rendered)
            output_response = await client.get(
                f"/api/v1/video/batches/{created['batch_id']}/outputs/douyin_vertical"
            )
            assert output_response.status_code == 200
            assert output_response.headers["content-type"].startswith("video/mp4")
            assert output_response.content.startswith(b"god-news-deterministic-video")

            persisted = await service.get(UUID(created["batch_id"]))
            assert persisted.artifact is not None
            assert not isinstance(persisted.artifact, LegacyVideoRenderArtifact)
            vertical = next(
                output
                for output in persisted.artifact.outputs
                if output.profile_id.value == "douyin_vertical"
            )
            output_path = Path(vertical.local_path)
            tampered = bytearray(await asyncio.to_thread(output_path.read_bytes))
            tampered[0] ^= 0xFF
            await asyncio.to_thread(output_path.write_bytes, tampered)
            changed_output = await client.get(
                f"/api/v1/video/batches/{created['batch_id']}/outputs/douyin_vertical"
            )
            assert changed_output.status_code == 409

            openapi = await client.get("/openapi.json")
            assert openapi.status_code == 200
            assert (
                openapi.json()["paths"][
                    "/api/v1/video/batches/{batch_id}/audio/{segment_id}"
                ]["get"]["operationId"]
                == "getVideoBatchAudioClip"
            )
            assert (
                openapi.json()["paths"][
                    "/api/v1/video/batches/{batch_id}/outputs/{profile_id}"
                ]["get"]["operationId"]
                == "getVideoBatchOutput"
            )


@pytest.mark.asyncio
async def test_video_batch_audio_preview_rejects_a_persisted_path_outside_output_root(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A community garden shared its harvest with neighbors.")
    service, repository, _, _ = _service(stack, tmp_path)
    stack.container.video_batches = service
    batch = await service.create(CreateVideoBatch(title="Safe preview", story_ids=[story.story_id]))
    synthesized = await _approve_and_synthesize(service, batch.batch_id, batch.version)
    assert synthesized.narration.audio is not None

    # Simulate a corrupted persisted record.  The route must still contain
    # the path even though normal synthesis already validates it.
    clip = synthesized.narration.audio.clips[0]
    invalid_audio = synthesized.narration.audio.model_copy(
        update={"clips": [clip.model_copy(update={"path": "../outside.wav"})]}
    )
    invalid_narration = synthesized.narration.model_copy(update={"audio": invalid_audio})
    repository._batches[synthesized.batch_id] = synthesized.model_copy(
        update={"narration": invalid_narration}
    )

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/video/batches/{synthesized.batch_id}/audio/{clip.segment_id}"
            )

    assert response.status_code == 409
    assert response.json()["code"] == "video_batch_conflict"


@pytest.mark.asyncio
async def test_local_bgm_catalog_is_stable_and_rejects_unknown_track(tmp_path: Path) -> None:
    root = tmp_path / "bgm"
    (root / "nested").mkdir(parents=True)
    (root / "Zeta.wav").write_bytes(b"z")
    (root / "nested" / "alpha.mp3").write_bytes(b"a")
    (root / "ignored.txt").write_text("not music", encoding="utf-8")
    (root / "empty.ogg").touch()
    catalog = LocalBgmCatalog(root)

    first = list(await catalog.list())
    second = list(await catalog.list())
    assert [item.relative_path for item in first] == ["nested/alpha.mp3", "Zeta.wav"]
    assert [item.track_id for item in first] == [item.track_id for item in second]
    (root / "nested" / "alpha.mp3").write_bytes(b"changed")
    changed = list(await catalog.list())
    assert changed[0].track_id != first[0].track_id
    selected = await catalog.resolve(changed[0].track_id, volume=0.2, loop=False)
    assert await AsyncPath(selected.local_path).is_file()
    assert selected.volume == 0.2
    assert selected.loop is False
    with pytest.raises(BgmTrackNotFoundError):
        await catalog.resolve("0" * 64, volume=0.2, loop=True)


def test_video_contract_rejects_remote_media_and_more_than_fifteen_stories() -> None:
    with pytest.raises(ValidationError):
        BgmSelection(track_id="0" * 64, local_path="https://example.com/music.mp3")
    with pytest.raises(ValidationError):
        CreateVideoBatch(title="Too many", story_ids=[uuid4() for _ in range(16)])
    with pytest.raises(ValidationError):
        SubmitNarrationReview(
            expected_batch_version=1,
            decision=NarrationReviewDecision.REVISE,
            reviewer_id="editor",
        )
