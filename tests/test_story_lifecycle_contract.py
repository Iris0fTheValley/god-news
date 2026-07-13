from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from god_news.api.app import create_app
from god_news.domain.enums import ReviewDecision, StoryStatus
from god_news.domain.models import (
    FirstReviewSubmission,
    IngestRequest,
    ScriptReviewSubmission,
    SecondReviewSubmission,
    StoryUpdate,
    SynthesizeStoryRequest,
    TextSource,
)
from god_news.errors import ConcurrentWriteError, InvalidTransitionError, StoryInvariantError

from .conftest import Stack


def _ingest_request() -> IngestRequest:
    return IngestRequest(
        source=TextSource(
            title="Original evidence headline",
            language="en",
            text="Neighbors returned a lost dog to its family after a storm.",
        ),
        target_language="zh-CN",
        style="accurate narration",
        target_duration_seconds=60,
    )


async def _complete_story(stack: Stack):  # type: ignore[no-untyped-def]
    story = await stack.workflow.ingest(_ingest_request())
    first = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="first-editor",
        ),
    )
    pending = await stack.workflow.submit_script_review(
        story.story_id,
        ScriptReviewSubmission(
            expected_story_version=first.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="script-editor",
        ),
    )
    synthesized = await stack.workflow.synthesize(
        story.story_id,
        SynthesizeStoryRequest(expected_story_version=pending.version),
    )
    return await stack.workflow.submit_second_review(
        story.story_id,
        SecondReviewSubmission(
            expected_story_version=synthesized.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="second-editor",
        ),
    )


@pytest.mark.asyncio
async def test_archive_is_a_soft_terminal_status_with_retained_evidence(stack: Stack) -> None:
    story = await stack.workflow.ingest(_ingest_request())
    archived = await stack.workflow.archive(story.story_id)

    assert archived.status is StoryStatus.ARCHIVED
    assert archived.version == story.version + 1
    assert archived.source == story.source
    assert archived.provenance == story.provenance
    assert archived.original_text == story.original_text
    assert (await stack.workflow.get(story.story_id)).status is StoryStatus.ARCHIVED
    assert await stack.workflow.list() == []
    assert [item.story_id for item in await stack.workflow.list(status=StoryStatus.ARCHIVED)] == [
        story.story_id
    ]
    assert [item.story_id for item in await stack.workflow.list(include_archived=True)] == [
        story.story_id
    ]

    transitions = await stack.workflow.transitions(story.story_id)
    assert (transitions[-1].from_status, transitions[-1].to_status) == (
        StoryStatus.PENDING_FIRST_REVIEW,
        StoryStatus.ARCHIVED,
    )
    assert transitions[-1].reason == "story archived"
    with pytest.raises(InvalidTransitionError):
        await stack.workflow.resume(story.story_id)


@pytest.mark.asyncio
async def test_only_done_stories_can_reopen_for_final_review(stack: Stack) -> None:
    done = await _complete_story(stack)
    reopened = await stack.workflow.reopen(done.story_id)

    assert reopened.status is StoryStatus.PENDING_SECOND_REVIEW
    assert reopened.version == done.version + 1
    assert reopened.script == done.script
    assert reopened.audio == done.audio
    transitions = await stack.workflow.transitions(done.story_id)
    assert (transitions[-1].from_status, transitions[-1].to_status) == (
        StoryStatus.DONE,
        StoryStatus.PENDING_SECOND_REVIEW,
    )
    assert transitions[-1].reason == "story reopened for final review"

    with pytest.raises(InvalidTransitionError):
        await stack.workflow.reopen(done.story_id)
    archived = await stack.workflow.archive(done.story_id)
    assert archived.status is StoryStatus.ARCHIVED
    with pytest.raises(InvalidTransitionError):
        await stack.workflow.reopen(done.story_id)


@pytest.mark.asyncio
async def test_patch_updates_only_editorial_fields_with_optimistic_concurrency(
    stack: Stack,
) -> None:
    story = await stack.workflow.ingest(_ingest_request())
    updated = await stack.workflow.update(
        story.story_id,
        StoryUpdate(
            expected_story_version=story.version,
            title="Edited editorial headline",
            style="warm concise narration",
            target_duration_seconds=75,
        ),
    )

    assert updated.title == "Edited editorial headline"
    assert updated.preferences.style == "warm concise narration"
    assert updated.preferences.target_duration_seconds == 75
    assert updated.source == story.source
    assert updated.source.title == "Original evidence headline"
    assert updated.provenance == story.provenance
    assert updated.original_text == story.original_text

    with pytest.raises(ConcurrentWriteError):
        await stack.workflow.update(
            story.story_id,
            StoryUpdate(expected_story_version=story.version, title="stale write"),
        )

    script_ready = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=updated.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="first-editor",
        ),
    )
    with pytest.raises(StoryInvariantError, match="cannot change after script generation"):
        await stack.workflow.update(
            story.story_id,
            StoryUpdate(
                expected_story_version=script_ready.version,
                style="too late to alter script inputs",
            ),
        )


@pytest.mark.asyncio
async def test_story_lifecycle_contract_is_exposed_over_http(stack: Stack) -> None:
    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/v1/stories",
                json={
                    "source": {
                        "kind": "text",
                        "title": "HTTP original evidence",
                        "language": "en",
                        "text": "A community center returned donated books to local children.",
                    },
                    "style": "accurate narration",
                    "target_duration_seconds": 60,
                },
            )
            assert created.status_code == 201
            story = created.json()
            story_id = story["story_id"]
            UUID(story_id)

            patched = await client.patch(
                f"/api/v1/stories/{story_id}",
                json={
                    "expected_story_version": story["version"],
                    "title": "HTTP editorial title",
                    "style": "brief warm narration",
                    "target_duration_seconds": 80,
                },
            )
            assert patched.status_code == 200
            assert patched.json()["title"] == "HTTP editorial title"
            assert patched.json()["source"]["title"] == "HTTP original evidence"

            invalid_patch = await client.patch(
                f"/api/v1/stories/{story_id}",
                json={"expected_story_version": patched.json()["version"]},
            )
            assert invalid_patch.status_code == 422
            provenance_patch = await client.patch(
                f"/api/v1/stories/{story_id}",
                json={
                    "expected_story_version": patched.json()["version"],
                    "source": {"title": "attempted source mutation"},
                },
            )
            assert provenance_patch.status_code == 422

            archived = await client.delete(f"/api/v1/stories/{story_id}")
            assert archived.status_code == 200
            assert archived.json()["status"] == "ARCHIVED"
            assert archived.json()["version"] == patched.json()["version"] + 1

            active = await client.get("/api/v1/stories")
            assert active.status_code == 200
            assert active.json() == []
            explicit_archives = await client.get(
                "/api/v1/stories",
                params={"status": "ARCHIVED"},
            )
            assert [item["story_id"] for item in explicit_archives.json()] == [story_id]
            fetched = await client.get(f"/api/v1/stories/{story_id}")
            assert fetched.status_code == 200
            assert fetched.json()["status"] == "ARCHIVED"

            assert (await client.post(f"/api/v1/stories/{story_id}/resume")).status_code == 409
            assert (await client.post(f"/api/v1/stories/{story_id}/reopen")).status_code == 409
            assert (
                await client.patch(
                    f"/api/v1/stories/{story_id}",
                    json={
                        "expected_story_version": archived.json()["version"],
                        "title": "archived write",
                    },
                )
            ).status_code == 409
