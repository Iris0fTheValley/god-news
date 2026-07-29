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
from god_news.infrastructure.video_visual_assets import ApprovedVisualAssetLibrary

from .test_fsm import make_artifacts, make_story


class _EmptyVisualRepository:
    async def list_for_script(self, story_id, *, script_revision):  # type: ignore[no-untyped-def]
        return []


class _DiscoveryRepository:
    def __init__(self, asset: PersistedVisualDiscoveryAsset) -> None:
        self.asset = asset

    async def list_for_story(
        self, story_id, *, script_revision: int  # type: ignore[no-untyped-def]
    ) -> list[PersistedVisualDiscoveryAsset]:
        if self.asset.story_id == story_id and self.asset.script_revision == script_revision:
            return [self.asset]
        return []


class _Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def resolve(self, storage_key: str) -> Path:
        assert storage_key == "commons/asset/portrait.jpg"
        return self.path


@pytest.mark.asyncio
async def test_approved_commons_image_enters_current_script_visual_snapshot(
    tmp_path: Path,
) -> None:
    story = make_story()
    translation, script, _audio = make_artifacts()
    story = transition_story(story, StoryStatus.TRANSLATED, translation=translation)
    story = transition_story(story, StoryStatus.PENDING_FIRST_REVIEW)
    story = transition_story(story, StoryStatus.PROCESSING_SCRIPT)
    story = transition_story(story, StoryStatus.SCRIPT_READY, script=script)
    image_path = tmp_path / "portrait.jpg"
    image_path.write_bytes(b"reviewed-image")
    candidate = CommonsVisualCandidate(
        file_title="File:Reviewed portrait.jpg",
        page_id=42,
        canonical_page_url="https://commons.wikimedia.org/wiki/File:Reviewed_portrait.jpg",
        direct_download_url="https://upload.wikimedia.org/reviewed-portrait.jpg",
        kind=CommonsMediaKind.IMAGE,
        mime_type="image/jpeg",
        width=1_200,
        height=1_600,
        size_bytes=image_path.stat().st_size,
        sha1="a" * 40,
        attribution={"attribution_text": "Example author"},
        rights={
            "license": "cc_by",
            "source_license_label": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "allows_commercial_use": True,
            "allows_derivatives": True,
            "requires_attribution": True,
            "requires_human_review": False,
        },
    )
    asset = PersistedVisualDiscoveryAsset(
        story_id=story.story_id,
        segment_id=script.segments[0].segment_id,
        script_revision=script.revision,
        status=VisualDiscoveryStatus.APPROVED,
        candidate=candidate,
        storage_key="commons/asset/portrait.jpg",
        sha256="b" * 64,
        downloaded_size_bytes=image_path.stat().st_size,
        created_at=utc_now(),
    )
    library = ApprovedVisualAssetLibrary(
        repository=_EmptyVisualRepository(),  # type: ignore[arg-type]
        store=_Store(image_path),  # type: ignore[arg-type]
        discovery_repository=_DiscoveryRepository(asset),  # type: ignore[arg-type]
        discovery_store=_Store(image_path),  # type: ignore[arg-type]
    )

    result = await library.approved_for_stories([story])

    render_asset = result[story.story_id][0]
    assert render_asset.asset_id == asset.asset_id
    assert render_asset.segment_id == script.segments[0].segment_id
    assert render_asset.local_path == str(image_path)
    assert render_asset.source_url == str(candidate.canonical_page_url)
    assert render_asset.source_label == "Example author · cc_by"
