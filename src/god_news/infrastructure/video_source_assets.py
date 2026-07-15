from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.domain.source_media import SourceMediaRepository
from god_news.domain.source_transcription import (
    SourceTranscriptionRepository,
    SourceTranscriptionStatus,
    VerifiedSourceMediaReader,
)
from god_news.domain.video import SourceVideoRenderAsset


class ApprovedSourceVideoAssetLibrary:
    """Join rights, immutable bytes, and final caption approval at one boundary."""

    def __init__(
        self,
        *,
        media_repository: SourceMediaRepository,
        transcription_repository: SourceTranscriptionRepository,
        media_reader: VerifiedSourceMediaReader,
    ) -> None:
        self._media_repository = media_repository
        self._transcription_repository = transcription_repository
        self._media_reader = media_reader

    async def approved_for_stories(
        self,
        story_ids: Sequence[UUID],
    ) -> Sequence[SourceVideoRenderAsset]:
        result: list[SourceVideoRenderAsset] = []
        for story_id in story_ids:
            artifacts = await self._media_repository.list_for_story(story_id)
            for artifact in artifacts:
                if not artifact.publish_eligible:
                    continue
                transcriptions = await self._transcription_repository.list_for_artifact(
                    artifact.artifact_id
                )
                approved = next(
                    (
                        item
                        for item in transcriptions
                        if item.status is SourceTranscriptionStatus.APPROVED
                        and item.artifact_sha256 == artifact.sha256
                    ),
                    None,
                )
                if approved is None:
                    continue
                verified, path = await self._media_reader.media_path(
                    story_id,
                    artifact.artifact_id,
                )
                if verified.sha256 != approved.artifact_sha256:
                    raise ValueError(
                        "Approved source transcription no longer matches its media artifact."
                    )
                result.append(
                    SourceVideoRenderAsset(
                        asset_id=verified.artifact_id,
                        story_id=story_id,
                        transcription_id=approved.transcription_id,
                        transcription_version=approved.version,
                        transcription_review=approved.reviews[-1],
                        local_path=str(path),
                        sha256=verified.sha256,
                        size_bytes=verified.size_bytes,
                        duration_ms=verified.probe.duration_ms,
                        width=verified.probe.width,
                        height=verified.probe.height,
                        out_ms=verified.probe.duration_ms,
                        source_label=verified.attribution.attribution_text,
                        captions=approved.cues,
                    )
                )
                # A first deterministic release uses at most one original clip
                # per story. Selection policy can evolve behind this port.
                break
        return result
