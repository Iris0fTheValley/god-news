from __future__ import annotations

import asyncio

import pytest

from god_news.domain.enums import ContentCategory, ReviewDecision, StoryStatus
from god_news.domain.models import (
    FirstReviewSubmission,
    IngestRequest,
    SecondReviewSubmission,
    TextSource,
)
from god_news.errors import ArtifactNotReadyError, IdempotencyConflictError, TTSGenerationError

from .conftest import Stack


def ingest_request() -> IngestRequest:
    return IngestRequest(
        source=TextSource(
            title="International fixture",
            language="en",
            text=(
                "The city council approved a renewable energy pilot on Tuesday. "
                "Officials said the twelve-month trial will publish monthly results."
            ),
        ),
        target_language="zh-CN",
        style="accurate narration",
        target_duration_seconds=60,
    )


@pytest.mark.asyncio
async def test_complete_review_gated_pipeline(stack: Stack) -> None:
    story = await stack.workflow.ingest(ingest_request())
    assert story.status is StoryStatus.PENDING_FIRST_REVIEW
    assert stack.synthesizer.calls == 0
    assert stack.generator.script_calls == 0
    assert stack.memory.writes == []

    with pytest.raises(ArtifactNotReadyError):
        await stack.workflow.production_manifest(story.story_id)

    story = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="editor-1",
            note="Names and quantities checked.",
        ),
    )
    assert story.status is StoryStatus.PENDING_SECOND_REVIEW
    assert stack.synthesizer.calls == 1
    assert story.audio is not None
    assert stack.memory.writes
    assert all(memory.approved for memory in stack.memory.writes)

    story = await stack.workflow.submit_second_review(
        story.story_id,
        SecondReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="editor-2",
            note="Audio and script approved.",
        ),
    )
    assert story.status is StoryStatus.DONE

    manifest = await stack.workflow.production_manifest(story.story_id)
    assert manifest.total_duration_ms > 0
    assert len(manifest.timeline) == len(story.script.segments)  # type: ignore[union-attr]

    transitions = await stack.workflow.transitions(story.story_id)
    assert [(item.from_status, item.to_status) for item in transitions] == [
        (StoryStatus.FETCHED, StoryStatus.TRANSLATED),
        (StoryStatus.TRANSLATED, StoryStatus.PENDING_FIRST_REVIEW),
        (StoryStatus.PENDING_FIRST_REVIEW, StoryStatus.PROCESSING_SCRIPT),
        (StoryStatus.PROCESSING_SCRIPT, StoryStatus.SCRIPT_READY),
        (StoryStatus.SCRIPT_READY, StoryStatus.PENDING_SECOND_REVIEW),
        (StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.DONE),
    ]
    assert len(await stack.workflow.reviews(story.story_id)) == 2
    assert any(memory.approved for memory in stack.memory.writes)


@pytest.mark.asyncio
async def test_first_review_changes_do_not_start_expensive_work(stack: Stack) -> None:
    story = await stack.workflow.ingest(ingest_request())
    story = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.REQUEST_CHANGES,
            reviewer_id="editor-1",
            note="Use a more precise summary.",
            corrected_summary="The council approved a twelve-month renewable energy pilot.",
            corrected_key_points=["Twelve-month pilot", "Monthly results"],
            corrected_category=ContentCategory.FORUM,
            corrected_candidate_recommendation=False,
        ),
    )
    assert story.status is StoryStatus.PENDING_FIRST_REVIEW
    assert story.translation is not None
    assert story.translation.summary.startswith("The council approved")
    assert story.translation.key_points == ["Twelve-month pilot", "Monthly results"]
    assert story.translation.screening.model_category is ContentCategory.KINDNESS
    assert story.translation.screening.category is ContentCategory.FORUM
    assert story.translation.screening.candidate_recommendation is False
    assert stack.synthesizer.calls == 0
    assert stack.generator.script_calls == 0
    review = (await stack.workflow.reviews(story.story_id))[0]
    assert review.ai_category is ContentCategory.KINDNESS
    assert review.human_category is ContentCategory.FORUM
    assert review.classification_accepted is False
    metrics = await stack.workflow.classification_metrics()
    assert metrics.reviewed_count == 1
    assert metrics.accepted_count == 0
    assert metrics.accuracy == 0.0


@pytest.mark.asyncio
async def test_tts_failure_is_recoverable_from_script_ready(stack: Stack) -> None:
    story = await stack.workflow.ingest(ingest_request())
    stack.synthesizer.fail_next = True
    with pytest.raises(TTSGenerationError):
        await stack.workflow.submit_first_review(
            story.story_id,
            FirstReviewSubmission(
                expected_story_version=story.version,
                decision=ReviewDecision.APPROVE,
                reviewer_id="editor-1",
            ),
        )
    failed = await stack.workflow.get(story.story_id)
    assert failed.status is StoryStatus.SCRIPT_READY
    assert failed.last_failure is not None

    resumed = await stack.workflow.resume(story.story_id)
    assert resumed.status is StoryStatus.PENDING_SECOND_REVIEW
    assert resumed.last_failure is None
    assert stack.synthesizer.calls == 2


@pytest.mark.asyncio
async def test_review_idempotency_prevents_duplicate_concurrent_tts(stack: Stack) -> None:
    story = await stack.workflow.ingest(ingest_request())
    submission = FirstReviewSubmission(
        expected_story_version=story.version,
        decision=ReviewDecision.APPROVE,
        reviewer_id="editor-1",
    )
    results = await asyncio.gather(
        stack.workflow.submit_first_review(story.story_id, submission),
        stack.workflow.submit_first_review(story.story_id, submission),
        return_exceptions=True,
    )
    assert all(not isinstance(result, Exception) for result in results)
    assert stack.synthesizer.calls == 1

    changed_request = submission.model_copy(update={"note": "different request"})
    with pytest.raises(IdempotencyConflictError):
        await stack.workflow.submit_first_review(story.story_id, changed_request)


@pytest.mark.asyncio
async def test_mismatched_audio_cannot_enter_second_review(stack: Stack) -> None:
    original_synthesize = stack.synthesizer.synthesize

    async def mismatched(story_id, script):  # type: ignore[no-untyped-def]
        audio = await original_synthesize(story_id, script)
        return audio.model_copy(update={"revision": script.revision + 1})

    stack.synthesizer.synthesize = mismatched  # type: ignore[method-assign]
    story = await stack.workflow.ingest(ingest_request())
    with pytest.raises(TTSGenerationError, match="does not match"):
        await stack.workflow.submit_first_review(
            story.story_id,
            FirstReviewSubmission(
                expected_story_version=story.version,
                decision=ReviewDecision.APPROVE,
                reviewer_id="editor-1",
            ),
        )
    failed = await stack.workflow.get(story.story_id)
    assert failed.status is StoryStatus.SCRIPT_READY
