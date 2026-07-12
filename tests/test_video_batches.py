from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from anyio import Path as AsyncPath
from pydantic import ValidationError

from god_news.api.app import create_app
from god_news.application.video_batches import VideoBatchService
from god_news.domain.enums import ContentCategory, ReviewDecision
from god_news.domain.models import (
    FirstReviewSubmission,
    IngestRequest,
    SecondReviewSubmission,
    TextSource,
)
from god_news.domain.video import (
    BgmSelection,
    CreateVideoBatch,
    SubmitTimelineReview,
    TimelineReviewDecision,
    VideoBatchStatus,
)
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.infrastructure.video_assets import LocalBgmCatalog
from god_news.infrastructure.video_host import PlaceholderHostRenderer
from god_news.infrastructure.video_repository import SqlAlchemyVideoBatchRepository
from god_news.infrastructure.video_testing import (
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
    story = await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="first-editor",
        ),
    )
    return await stack.workflow.submit_second_review(
        story.story_id,
        SecondReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="final-editor",
        ),
    )


def _service(
    stack: Stack,
    tmp_path: Path,
) -> tuple[VideoBatchService, InMemoryVideoBatchRepository, DeterministicBatchVideoRenderer]:
    repository = InMemoryVideoBatchRepository()
    renderer = DeterministicBatchVideoRenderer(tmp_path / "videos")
    service = VideoBatchService(
        story_pool=stack.workflow,
        repository=repository,
        host_renderer=PlaceholderHostRenderer(),
        video_renderer=renderer,
        bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
        audio_root=stack.settings.output_dir,
    )
    return service, repository, renderer


@pytest.mark.asyncio
async def test_video_batch_has_deterministic_order_review_gate_and_used_at(
    stack: Stack,
    tmp_path: Path,
) -> None:
    kindness = await _done_story(stack, "A neighbor quietly helped carry groceries home.")
    short_video = await _done_story(stack, "A short video clip records a careful rescue.")
    cats_dogs = await _done_story(stack, "A dog waited beside a lost child until help came.")
    forum = await _done_story(stack, "A Reddit forum thanked volunteers after the storm.")

    bgm_dir = tmp_path / "bgm"
    bgm_dir.mkdir()
    (bgm_dir / "calm.mp3").write_bytes(b"local-bgm")
    service, _, renderer = _service(stack, tmp_path)
    track = (await service.list_bgm())[0]

    batch = await service.create(
        CreateVideoBatch(
            title="Daily kindness",
            story_ids=[forum.story_id, cats_dogs.story_id, kindness.story_id, short_video.story_id],
            max_stories=4,
            bgm_track_id=track.track_id,
        )
    )

    assert batch.status is VideoBatchStatus.PENDING_TIMELINE_REVIEW
    assert [story.category for story in batch.stories] == [
        ContentCategory.KINDNESS,
        ContentCategory.SHORT_VIDEO,
        ContentCategory.CATS_DOGS,
        ContentCategory.FORUM,
    ]
    assert [story.sequence for story in batch.stories] == [0, 1, 2, 3]
    assert all(story.used_at is None for story in batch.stories)
    assert batch.bgm is not None
    assert batch.remotion_props.bgm is not None
    assert batch.remotion_props.bgm.model_dump() == {
        "local_path": batch.bgm.local_path,
        "volume": 0.12,
        "loop": True,
    }
    assert batch.remotion_props.visual_reservations.renderer == "placeholder"

    with pytest.raises(VideoBatchConflictError):
        await service.render(batch.batch_id, expected_version=batch.version)
    assert renderer.calls == 0

    human_order = [story.story_id for story in reversed(batch.stories)]
    reviewed = await service.submit_timeline_review(
        batch.batch_id,
        SubmitTimelineReview(
            expected_batch_version=batch.version,
            decision=TimelineReviewDecision.APPROVE,
            reviewer_id="timeline-editor",
            story_order=human_order,
        ),
    )
    assert reviewed.status is VideoBatchStatus.READY_TO_RENDER
    assert [story.story_id for story in reviewed.stories] == human_order
    assert [story.chapter_start_ms for story in reviewed.stories] == [
        0,
        reviewed.stories[0].chapter_end_ms,
        reviewed.stories[1].chapter_end_ms,
        reviewed.stories[2].chapter_end_ms,
    ]

    rendered = await service.render(reviewed.batch_id, expected_version=reviewed.version)
    assert rendered.status is VideoBatchStatus.RENDERED
    assert rendered.artifact is not None
    assert await AsyncPath(rendered.artifact.local_path).is_file()
    used_at = {story.used_at for story in rendered.stories}
    assert len(used_at) == 1
    assert None not in used_at

    with pytest.raises(VideoStoryUnavailableError):
        await service.create(
            CreateVideoBatch(
                title="Cannot reuse",
                story_ids=[kindness.story_id],
                max_stories=1,
            )
        )


@pytest.mark.asyncio
async def test_rejected_batch_releases_story_claim(stack: Stack, tmp_path: Path) -> None:
    story = await _done_story(stack, "A teacher donated books to a small library.")
    service, _, _ = _service(stack, tmp_path)
    pending = await service.create(
        CreateVideoBatch(title="Rejected cut", story_ids=[story.story_id], max_stories=1)
    )
    rejected = await service.submit_timeline_review(
        pending.batch_id,
        SubmitTimelineReview(
            expected_batch_version=pending.version,
            decision=TimelineReviewDecision.REJECT,
            reviewer_id="timeline-editor",
            note="The edition needs a different theme.",
        ),
    )
    assert rejected.status is VideoBatchStatus.REJECTED
    assert rejected.stories[0].used_at is None

    replacement = await service.create(
        CreateVideoBatch(title="Replacement cut", story_ids=[story.story_id], max_stories=1)
    )
    assert replacement.status is VideoBatchStatus.PENDING_TIMELINE_REVIEW


@pytest.mark.asyncio
async def test_cancelled_or_deleted_batch_releases_unrendered_story_claims(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "Residents planted flowers around the bus stop.")
    service, _, _ = _service(stack, tmp_path)
    pending = await service.create(
        CreateVideoBatch(title="Cancelled cut", story_ids=[story.story_id], max_stories=1)
    )
    cancelled = await service.cancel(pending.batch_id)
    assert cancelled.status is VideoBatchStatus.CANCELLED
    replacement = await service.create(
        CreateVideoBatch(
            title="Replacement after cancel",
            story_ids=[story.story_id],
            max_stories=1,
        )
    )
    await service.delete(replacement.batch_id)
    final = await service.create(
        CreateVideoBatch(
            title="Replacement after delete",
            story_ids=[story.story_id],
            max_stories=1,
        )
    )
    assert final.status is VideoBatchStatus.PENDING_TIMELINE_REVIEW


@pytest.mark.asyncio
async def test_failed_render_keeps_claim_and_can_retry(stack: Stack, tmp_path: Path) -> None:
    story = await _done_story(stack, "Volunteers repaired a playground before school opened.")
    service, _, renderer = _service(stack, tmp_path)
    pending = await service.create(
        CreateVideoBatch(title="Retryable cut", story_ids=[story.story_id], max_stories=1)
    )
    approved = await service.submit_timeline_review(
        pending.batch_id,
        SubmitTimelineReview(
            expected_batch_version=pending.version,
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
    assert failed.stories[0].used_at is None
    with pytest.raises(VideoStoryUnavailableError):
        await service.create(
            CreateVideoBatch(title="Still claimed", story_ids=[story.story_id], max_stories=1)
        )

    rendered = await service.render(failed.batch_id, expected_version=failed.version)
    assert rendered.status is VideoBatchStatus.RENDERED
    assert renderer.calls == 2


@pytest.mark.asyncio
async def test_render_rejects_mutated_assets_after_timeline_approval(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A neighbor repaired a wheelchair ramp overnight.")
    bgm_dir = tmp_path / "bgm"
    bgm_dir.mkdir()
    track_path = bgm_dir / "calm.mp3"
    track_path.write_bytes(b"approved-bgm")
    service, _, renderer = _service(stack, tmp_path)
    track = (await service.list_bgm())[0]
    pending = await service.create(
        CreateVideoBatch(
            title="Immutable input cut",
            story_ids=[story.story_id],
            max_stories=1,
            bgm_track_id=track.track_id,
        )
    )
    approved = await service.submit_timeline_review(
        pending.batch_id,
        SubmitTimelineReview(
            expected_batch_version=pending.version,
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
        BgmSelection(
            track_id="0" * 64,
            local_path="https://example.com/music.mp3",
        )
    with pytest.raises(ValidationError):
        CreateVideoBatch(
            title="Too many",
            story_ids=[uuid4() for _ in range(16)],
        )


@pytest.mark.asyncio
async def test_sql_repository_persists_claim_and_used_at_atomically(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A nurse organized free checkups for elderly neighbors.")
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
            video_renderer=renderer,
            bgm_catalog=LocalBgmCatalog(tmp_path / "bgm"),
            audio_root=stack.settings.output_dir,
        )
        pending = await service.create(
            CreateVideoBatch(title="Persistent cut", story_ids=[story.story_id], max_stories=1)
        )
        approved = await service.submit_timeline_review(
            pending.batch_id,
            SubmitTimelineReview(
                expected_batch_version=pending.version,
                decision=TimelineReviewDecision.APPROVE,
                reviewer_id="timeline-editor",
            ),
        )
        rendered = await service.render(approved.batch_id, expected_version=approved.version)

        reloaded = await repository.get(rendered.batch_id)
        assert reloaded.status is VideoBatchStatus.RENDERED
        assert reloaded.stories[0].used_at == rendered.stories[0].used_at
        assert await repository.unavailable_story_ids([story.story_id]) == {story.story_id}
        with pytest.raises(VideoStoryUnavailableError):
            await service.create(
                CreateVideoBatch(title="Duplicate cut", story_ids=[story.story_id], max_stories=1)
            )
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_video_api_exposes_batch_review_and_render_gate(
    stack: Stack,
    tmp_path: Path,
) -> None:
    story = await _done_story(stack, "A baker shared breakfast with stranded commuters.")
    service, _, _ = _service(stack, tmp_path)
    stack.container.video_batches = service

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/v1/video/batches",
                json={
                    "title": "API cut",
                    "story_ids": [str(story.story_id)],
                    "max_stories": 1,
                },
            )
            assert created.status_code == 201
            pending = created.json()
            assert pending["status"] == "PENDING_TIMELINE_REVIEW"

            blocked = await client.post(
                f"/api/v1/video/batches/{pending['batch_id']}/render",
                json={"expected_batch_version": pending["version"]},
            )
            assert blocked.status_code == 409

            approved_response = await client.post(
                f"/api/v1/video/batches/{pending['batch_id']}/timeline-review",
                json={
                    "expected_batch_version": pending["version"],
                    "decision": "approve",
                    "reviewer_id": "timeline-editor",
                },
            )
            assert approved_response.status_code == 200
            approved = approved_response.json()
            assert approved["status"] == "READY_TO_RENDER"

            rendered = await client.post(
                f"/api/v1/video/batches/{pending['batch_id']}/render",
                json={"expected_batch_version": approved["version"]},
            )
            assert rendered.status_code == 200
            assert rendered.json()["status"] == "RENDERED"
            assert rendered.json()["stories"][0]["used_at"] is not None

            listed = await client.get(
                "/api/v1/video/batches",
                params={"status": "RENDERED"},
            )
            assert listed.status_code == 200
            assert [item["batch_id"] for item in listed.json()] == [pending["batch_id"]]
