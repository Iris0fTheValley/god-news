from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from god_news.domain.models import CaptionVariant
from god_news.domain.source_media import SourceVideoProbe, StoredSourceMediaArtifact
from god_news.domain.source_transcription import (
    SourceMediaTranscription,
    SourceTranscriptionStatus,
    TimedCaptionCue,
    TranscriptReview,
    TranscriptReviewDecision,
)
from god_news.infrastructure.video_source_assets import ApprovedSourceVideoAssetLibrary
from god_news.sources.models import Attribution, RightsMetadata


class _MediaRepository:
    def __init__(self, artifacts: Sequence[StoredSourceMediaArtifact]) -> None:
        self.artifacts = list(artifacts)

    async def list_for_story(self, story_id: UUID) -> Sequence[StoredSourceMediaArtifact]:
        return [item for item in self.artifacts if item.story_id == story_id]


class _TranscriptionRepository:
    def __init__(self, transcriptions: Sequence[SourceMediaTranscription]) -> None:
        self.transcriptions = list(transcriptions)

    async def list_for_artifact(
        self,
        artifact_id: UUID,
    ) -> Sequence[SourceMediaTranscription]:
        return [item for item in self.transcriptions if item.artifact_id == artifact_id]


class _MediaReader:
    def __init__(self, artifacts: Sequence[StoredSourceMediaArtifact], path: Path) -> None:
        self.artifacts = {item.artifact_id: item for item in artifacts}
        self.path = path

    async def media_path(self, story_id: UUID, artifact_id: UUID):  # type: ignore[no-untyped-def]
        artifact = self.artifacts[artifact_id]
        assert artifact.story_id == story_id
        return artifact, self.path


def _artifact(
    *,
    story_id: UUID,
    publish_eligible: bool,
    payload: bytes,
) -> StoredSourceMediaArtifact:
    rights = RightsMetadata(
        status="public_domain" if publish_eligible else "unknown",
        copyright_holder=None,
        license_name="Public domain" if publish_eligible else None,
        license_url=None,
        terms_url=None,
        allows_republication=True if publish_eligible else None,
        allows_derivatives=True if publish_eligible else None,
        requires_attribution=True,
        requires_human_review=not publish_eligible,
    )
    return StoredSourceMediaArtifact(
        story_id=story_id,
        source="reddit",
        media_index=0,
        acquired_by="media-editor",
        source_url="https://example.com/source.mp4",
        canonical_story_url="https://example.com/story",
        attribution=Attribution(
            source="reddit",
            publisher="Example publisher",
            original_url="https://example.com/story",
            author="Example author",
            attribution_text="Example publisher / Example author",
        ),
        rights=rights,
        publish_eligible=publish_eligible,
        content_type="video/mp4",
        filename="source.mp4",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        probe=SourceVideoProbe(
            duration_ms=8_000,
            width=1_920,
            height=1_080,
            video_codec="h264",
            audio_codec="aac",
            fps=30,
        ),
        storage_key="fixture/source.mp4",
    )


def _approved_transcription(artifact: StoredSourceMediaArtifact) -> SourceMediaTranscription:
    review = TranscriptReview(
        reviewer_id="caption-editor",
        decision=TranscriptReviewDecision.APPROVE,
        reviewed_version=1,
    )
    return SourceMediaTranscription(
        story_id=artifact.story_id,
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        model_identity="fixture-asr",
        target_caption_language="zh-CN",
        status=SourceTranscriptionStatus.APPROVED,
        requested_by="caption-editor",
        attempt_count=1,
        detected_language="en",
        language_probability=0.99,
        cues=[
            TimedCaptionCue(
                sequence=0,
                start_ms=0,
                end_ms=8_000,
                captions=[
                    CaptionVariant(language="en", kind="verbatim", text="A kind moment."),
                    CaptionVariant(language="zh-CN", kind="translation", text="一个善意瞬间。"),
                ],
            )
        ],
        reviews=[review],
        version=2,
    )


@pytest.mark.asyncio
async def test_library_requires_both_publishable_rights_and_final_transcript_approval(
    tmp_path: Path,
) -> None:
    payload = b"approved source video"
    path = tmp_path / "source.mp4"
    path.write_bytes(payload)
    allowed_story = uuid4()
    blocked_story = uuid4()
    allowed = _artifact(story_id=allowed_story, publish_eligible=True, payload=payload)
    blocked = _artifact(story_id=blocked_story, publish_eligible=False, payload=payload)
    library = ApprovedSourceVideoAssetLibrary(
        media_repository=_MediaRepository([allowed, blocked]),  # type: ignore[arg-type]
        transcription_repository=_TranscriptionRepository(
            [_approved_transcription(allowed), _approved_transcription(blocked)]
        ),  # type: ignore[arg-type]
        media_reader=_MediaReader([allowed, blocked], path),
    )

    assets = list(await library.approved_for_stories([blocked_story, allowed_story]))

    assert len(assets) == 1
    assert assets[0].story_id == allowed_story
    assert assets[0].sha256 == allowed.sha256
    assert assets[0].transcription_review.decision is TranscriptReviewDecision.APPROVE
    assert assets[0].captions[0].captions[1].text == "一个善意瞬间。"
    assert assets[0].local_path == str(path)
