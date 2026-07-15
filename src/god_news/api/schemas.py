from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from god_news.domain.enums import AudioFormat, SceneTransition, SpeechEmotion
from god_news.domain.models import ScriptDocument, SynthesisMetadata
from god_news.domain.video import (
    BatchNarrationFailure,
    BatchNarrationSourceEvidence,
    NarrationReview,
    TimelineReview,
    VideoBatchStatus,
    VideoOutputProfile,
    VideoOutputProfileId,
    VideoRenderFailure,
    VideoTheme,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Liveness(ApiModel):
    alive: bool = True


class ProblemDetail(ApiModel):
    code: str
    message: str
    trace_id: str
    story_id: UUID | None = None


class PublicVideoRenderOutput(ApiModel):
    profile_id: VideoOutputProfileId
    local_path: str = Field(exclude=True)
    size_bytes: int
    sha256: str
    width: int
    height: int
    fps: int
    duration_in_frames: int
    video_codec: str
    audio_codec: str


class PublicVideoRenderArtifact(ApiModel):
    renderer: str
    outputs: list[PublicVideoRenderOutput]
    rendered_at: datetime


class PublicLegacyVideoRenderArtifact(ApiModel):
    local_path: str = Field(exclude=True)
    size_bytes: int
    sha256: str
    renderer: str
    rendered_at: datetime


class PublicVideoInputAsset(ApiModel):
    kind: str
    local_path: str = Field(exclude=True)
    sha256: str
    size_bytes: int


class PublicBgmSelection(ApiModel):
    track_id: str
    local_path: str = Field(exclude=True)
    volume: float
    loop: bool


class PublicBgmRenderSpec(ApiModel):
    local_path: str = Field(exclude=True)
    volume: float
    loop: bool


class PublicAudioClip(ApiModel):
    segment_id: UUID
    path: str = Field(exclude=True)
    format: AudioFormat
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sha256: str


class PublicAudioBundle(ApiModel):
    revision: int
    provider: str
    model_identity: str
    synthesis: SynthesisMetadata
    generated_at: datetime
    clips: list[PublicAudioClip]


class PublicTimelineSegment(ApiModel):
    segment_id: UUID
    sequence: int
    start_ms: int
    end_ms: int
    text: str
    speaker_id: str
    emotion: SpeechEmotion
    scene_transition: SceneTransition
    visual_hint: str | None = None
    audio_path: str = Field(exclude=True)


class PublicProductionManifest(ApiModel):
    schema_version: Literal["1.0"]
    story_id: UUID
    script_revision: int
    language: str
    total_duration_ms: int
    timeline: list[PublicTimelineSegment]


class PublicLive2DReservation(ApiModel):
    character_id: str
    model_json_path: str = Field(exclude=True)
    idle_motion_group: str | None = None


class PublicDifferentialArtLayer(ApiModel):
    layer_id: str
    image_path: str = Field(exclude=True)
    z_index: int


class PublicDifferentialArtReservation(ApiModel):
    base_image_path: str = Field(exclude=True)
    layers: list[PublicDifferentialArtLayer]


class PublicHostVisualReservations(ApiModel):
    renderer: Literal["placeholder"]
    live2d: PublicLive2DReservation | None = None
    differential_art: PublicDifferentialArtReservation | None = None


class PublicBatchNarrationArtifact(ApiModel):
    source_evidence: list[BatchNarrationSourceEvidence]
    source_evidence_sha256: str
    script: ScriptDocument
    audio: PublicAudioBundle | None = None
    manifest: PublicProductionManifest | None = None
    composed_at: datetime
    synthesized_at: datetime | None = None


class PublicRemotionVideoProps(ApiModel):
    manifest: PublicProductionManifest
    title: str
    subtitle: str | None = None
    intro_duration_ms: int
    transition_duration_ms: int
    theme: VideoTheme
    bgm: PublicBgmRenderSpec | None = None
    visual_reservations: PublicHostVisualReservations
    output_profiles: list[VideoOutputProfile]


class PublicVideoBatchStory(ApiModel):
    sequence: int
    story_id: UUID
    story_version: int
    category: str
    title: str
    script: ScriptDocument
    script_sha256: str
    source_manifest: PublicProductionManifest
    source_manifest_sha256: str
    reserved_at: datetime
    used_at: datetime | None = None


class PublicVideoBatch(ApiModel):
    batch_id: UUID
    status: VideoBatchStatus
    title: str
    subtitle: str | None = None
    stories: list[PublicVideoBatchStory]
    narration: PublicBatchNarrationArtifact
    bgm: PublicBgmSelection | None = None
    visual_reservations: PublicHostVisualReservations
    remotion_props: PublicRemotionVideoProps | None = None
    input_assets: list[PublicVideoInputAsset]
    render_input_sha256: str | None = None
    narration_reviews: list[NarrationReview]
    timeline_review: TimelineReview | None = None
    artifact: PublicVideoRenderArtifact | PublicLegacyVideoRenderArtifact | None = None
    narration_failure: BatchNarrationFailure | None = None
    last_failure: VideoRenderFailure | None = None
    version: int
    created_at: datetime
    updated_at: datetime
