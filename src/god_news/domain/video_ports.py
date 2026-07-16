from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.enums import StoryStatus
from god_news.domain.models import AudioBundle, ProductionManifest, ScriptDocument, Story
from god_news.domain.video import (
    BgmSelection,
    BgmTrack,
    DirectedProgramDraft,
    HostVisualReservations,
    RemotionVideoProps,
    SourceVideoRenderAsset,
    VideoBatch,
    VideoBatchStatus,
    VideoBatchStory,
    VideoInputAsset,
    VideoRenderArtifact,
    VisualRenderAsset,
)


class StoryManifestPool(Protocol):
    async def get(self, story_id: UUID) -> Story: ...

    async def list(
        self,
        *,
        status: StoryStatus | None,
        limit: int,
        offset: int,
    ) -> Sequence[Story]: ...

    async def production_manifest(self, story_id: UUID) -> ProductionManifest: ...


class HostRenderer(Protocol):
    """Replaceable visual-host preparation boundary.

    Disabled deployments may return an explicit empty reservation, while the
    production Live2D adapter populates immutable per-segment media and
    diagnostics. Future host renderers can use the same typed boundary without
    changing batch selection, review, persistence, or render orchestration.
    """

    @property
    def name(self) -> str: ...

    async def prepare(
        self,
        *,
        batch_id: UUID,
        script: ScriptDocument,
        audio: AudioBundle,
    ) -> HostVisualReservations: ...


class ProgramDirector(Protocol):
    """Direct immutable story scripts into one reviewable program.

    A future LLM, rules engine, or human-assisted director can change only this
    boundary. It returns typed editorial semantics plus a compiled script while
    batch storage, TTS, asset snapshotting, and rendering stay independent.
    """

    @property
    def name(self) -> str: ...

    async def direct(
        self,
        *,
        batch_id: UUID,
        title: str,
        sources: Sequence[VideoBatchStory],
        source_video_story_ids: frozenset[UUID],
    ) -> DirectedProgramDraft: ...


class BgmCatalog(Protocol):
    async def list(self) -> Sequence[BgmTrack]: ...

    async def resolve(
        self,
        track_id: str,
        *,
        volume: float,
        loop: bool,
    ) -> BgmSelection: ...


class SourceVideoAssetLibrary(Protocol):
    """Resolve only immutable, publishable, transcript-approved source video."""

    async def approved_for_stories(
        self,
        story_ids: Sequence[UUID],
    ) -> Sequence[SourceVideoRenderAsset]: ...


class VisualAssetLibrary(Protocol):
    """Resolve only current, revision-bound raster evidence for batch snapshots."""

    async def approved_for_stories(
        self,
        stories: Sequence[Story],
    ) -> dict[UUID, Sequence[VisualRenderAsset]]: ...


class BatchVideoRenderer(Protocol):
    @property
    def name(self) -> str: ...

    async def render(
        self,
        batch_id: UUID,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> VideoRenderArtifact: ...

    async def cleanup_interrupted(self, batch_ids: Sequence[UUID]) -> int: ...


class VideoBatchRepository(Protocol):
    async def create(self, batch: VideoBatch) -> VideoBatch: ...

    async def get(self, batch_id: UUID) -> VideoBatch: ...

    async def list(
        self,
        *,
        status: VideoBatchStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[VideoBatch]: ...

    async def unavailable_story_ids(self, story_ids: Sequence[UUID]) -> frozenset[UUID]: ...

    async def save(self, batch: VideoBatch, *, expected_version: int) -> VideoBatch: ...

    async def recover_interrupted_rendering(self) -> Sequence[UUID]: ...

    async def delete(self, batch_id: UUID) -> None: ...

    async def protected_asset_paths(self) -> Sequence[Path]: ...

    async def healthcheck(self) -> None: ...
