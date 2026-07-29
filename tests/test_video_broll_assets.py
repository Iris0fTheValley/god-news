from __future__ import annotations

from pathlib import Path

import pytest

from god_news.domain.enums import StoryStatus
from god_news.domain.fsm import transition_story
from god_news.domain.models import utc_now
from god_news.domain.visual_discovery import (
    CommonsMediaKind,
    CommonsVisualCandidate,
    PersistedVisualDiscoveryAsset,
    VisualDiscoveryStatus,
)
from god_news.infrastructure.testing import InMemoryStoryRepository
from god_news.infrastructure.video_broll_assets import ApprovedVisualDiscoveryBrollLibrary

from .test_fsm import make_artifacts, make_story


class _Repository:
    def __init__(self, asset: PersistedVisualDiscoveryAsset) -> None:
        self.asset = asset
        self.requested_revision: int | None = None

    async def list_for_story(
        self, story_id, *, script_revision: int  # type: ignore[no-untyped-def]
    ) -> list[PersistedVisualDiscoveryAsset]:
        self.requested_revision = script_revision
        if self.asset.story_id == story_id and self.asset.script_revision == script_revision:
            return [self.asset]
        return []


class _Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def resolve(self, storage_key: str) -> Path:
        assert storage_key == "commons/asset/original.webm"
        return self.path


@pytest.mark.asyncio
async def test_approved_commons_video_adapts_to_current_revision_broll(tmp_path: Path) -> None:
    story = make_story()
    translation, script, _audio = make_artifacts()
    story = transition_story(story, StoryStatus.TRANSLATED, translation=translation)
    story = transition_story(story, StoryStatus.PENDING_FIRST_REVIEW)
    story = transition_story(story, StoryStatus.PROCESSING_SCRIPT)
    story = transition_story(story, StoryStatus.SCRIPT_READY, script=script)
    stories = InMemoryStoryRepository()
    await stories.create(story)
    media_path = tmp_path / "moon.webm"
    media_path.write_bytes(b"verified-video-fixture")
    candidate = CommonsVisualCandidate(
        file_title="File:Moon transit.webm",
        page_id=4250664,
        canonical_page_url="https://commons.wikimedia.org/wiki/File:Moon_transit.webm",
        direct_download_url="https://upload.wikimedia.org/moon.webm",
        kind=CommonsMediaKind.VIDEO,
        mime_type="video/webm",
        width=640,
        height=480,
        duration_ms=7_933,
        size_bytes=media_path.stat().st_size,
        sha1="a" * 40,
        attribution={"attribution_text": "NASA · Public domain"},
        rights={
            "license": "public_domain",
            "allows_commercial_use": True,
            "allows_derivatives": True,
            "requires_attribution": False,
            "requires_human_review": False,
        },
    )
    asset = PersistedVisualDiscoveryAsset(
        story_id=story.story_id,
        segment_id=script.segments[0].segment_id,
        script_revision=script.revision,
        status=VisualDiscoveryStatus.APPROVED,
        candidate=candidate,
        storage_key="commons/asset/original.webm",
        sha256="b" * 64,
        downloaded_size_bytes=media_path.stat().st_size,
        probed_duration_ms=7_933,
        created_at=utc_now(),
    )
    repository = _Repository(asset)
    library = ApprovedVisualDiscoveryBrollLibrary(
        stories=stories,
        repository=repository,  # type: ignore[arg-type]
        store=_Store(media_path),  # type: ignore[arg-type]
    )

    result = await library.approved_for_stories([story.story_id])

    assert repository.requested_revision == script.revision
    assert len(result) == 1
    render_asset = result[0]
    assert render_asset.asset_id == asset.asset_id
    assert render_asset.segment_id == script.segments[0].segment_id
    assert render_asset.audio_mode == "muted"
    assert render_asset.out_ms == 7_933
    assert render_asset.attribution == "NASA · Public domain"
