from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, field_validator, model_validator

from god_news.domain.enums import ContentCategory, SceneTransition
from god_news.domain.models import (
    AudioBundle,
    DomainModel,
    NonBlankStr,
    ProductionManifest,
    ScriptDocument,
    utc_now,
)
from god_news.domain.source_transcription import (
    TimedCaptionCue,
    TranscriptReview,
    TranscriptReviewDecision,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
TemplateId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
TemplateVersion = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
]
SceneVariantId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]


def _canonical_sha256(value: object) -> str:
    """Hash a JSON-safe value without depending on formatting or key order."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def model_sha256(model: DomainModel) -> str:
    """Stable evidence digest for an immutable Pydantic domain artifact."""

    return _canonical_sha256(model.model_dump(mode="json"))


class VideoBatchStatus(StrEnum):
    """Batch workflow deliberately separates editorial and expensive work."""

    PENDING_NARRATION_REVIEW = "PENDING_NARRATION_REVIEW"
    PENDING_BATCH_TTS = "PENDING_BATCH_TTS"
    PROCESSING_BATCH_TTS = "PROCESSING_BATCH_TTS"
    PENDING_TIMELINE_REVIEW = "PENDING_TIMELINE_REVIEW"
    READY_TO_RENDER = "READY_TO_RENDER"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class NarrationReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class TimelineReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


def _require_local_path(value: str) -> str:
    """Reject URI and UNC inputs at the domain boundary.

    Relative paths and local drive paths are accepted. Infrastructure adapters
    still resolve and contain the path within their configured roots.
    """

    candidate = value.strip()
    if not candidate:
        raise ValueError("local path cannot be blank")
    if candidate.startswith(("\\\\", "//")):
        raise ValueError("UNC/network paths are not allowed")
    if re.match(r"^[a-zA-Z]:[\\/]", candidate):
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        raise ValueError("URI assets are not allowed; select a local file")
    return candidate


class BgmTrack(DomainModel):
    track_id: Sha256
    relative_path: NonBlankStr
    display_name: NonBlankStr
    size_bytes: int = Field(gt=0)


class BgmSelection(DomainModel):
    track_id: Sha256
    local_path: NonBlankStr
    volume: float = Field(default=0.12, ge=0, le=1)
    loop: bool = True

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)

    def render_spec(self) -> BgmRenderSpec:
        return BgmRenderSpec(
            local_path=self.local_path,
            volume=self.volume,
            loop=self.loop,
        )


class BgmRenderSpec(DomainModel):
    local_path: NonBlankStr
    volume: float = Field(default=0.12, ge=0, le=1)
    loop: bool = True

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class VideoInputAssetKind(StrEnum):
    AUDIO = "audio"
    BGM = "bgm"
    HOST_VIDEO = "host_video"
    SOURCE_VIDEO = "source_video"
    IMAGE = "image"
    SOURCE_SCREENSHOT = "source_screenshot"


class VideoInputAsset(DomainModel):
    """Immutable evidence for a local file approved for a render."""

    kind: VideoInputAssetKind
    local_path: NonBlankStr
    sha256: Sha256
    size_bytes: int = Field(gt=0)

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class VideoTheme(DomainModel):
    background: HexColor = "#101512"
    foreground: HexColor = "#f3f1e8"
    accent: HexColor = "#85a77d"
    signal: HexColor = "#e4a853"


class VisualAssetType(StrEnum):
    IMAGE = "image"
    SOURCE_SCREENSHOT = "source_screenshot"
    WEB_EVIDENCE = "web_evidence"
    SOURCE_VIDEO = "source_video"
    MAP = "map"
    CHART = "chart"
    DOCUMENT = "document"
    HOST_VIDEO = "host_video"
    BACKGROUND_VIDEO = "background_video"
    DECORATIVE_OVERLAY = "decorative_overlay"


class VisualRenderAsset(DomainModel):
    """Immutable reviewed raster evidence consumed by semantic scenes."""

    asset_id: UUID
    story_id: UUID
    segment_id: UUID | None = None
    asset_type: VisualAssetType
    content_type: NonBlankStr
    filename: NonBlankStr
    local_path: NonBlankStr
    sha256: Sha256
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0, le=16_384)
    height: int = Field(gt=0, le=16_384)
    source_label: NonBlankStr
    source_url: str | None = None

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)

    @model_validator(mode="after")
    def validate_binding(self) -> VisualRenderAsset:
        if self.asset_type is VisualAssetType.IMAGE and self.segment_id is None:
            raise ValueError("editor images must bind to a narration segment")
        if self.asset_type is VisualAssetType.SOURCE_SCREENSHOT and self.segment_id is not None:
            raise ValueError("source screenshots are story-level evidence")
        return self


class Live2DReservation(DomainModel):
    character_id: NonBlankStr
    model_json_path: NonBlankStr
    idle_motion_group: NonBlankStr | None = None

    @field_validator("model_json_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class DifferentialArtLayer(DomainModel):
    layer_id: NonBlankStr
    image_path: NonBlankStr
    z_index: int

    @field_validator("image_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class DifferentialArtReservation(DomainModel):
    base_image_path: NonBlankStr
    layers: list[DifferentialArtLayer] = Field(default_factory=list, max_length=64)

    @field_validator("base_image_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class Live2DSignalMetrics(DomainModel):
    samples: int = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    minimum: float
    maximum: float
    p95_absolute_value: float = Field(ge=0)
    p99_absolute_value: float = Field(ge=0)
    maximum_absolute_value: float = Field(ge=0)
    p95_absolute_step: float = Field(ge=0)
    p99_absolute_step: float = Field(ge=0)
    maximum_absolute_step: float = Field(ge=0)
    p95_absolute_velocity: float = Field(ge=0)
    maximum_absolute_velocity: float = Field(ge=0)
    p95_absolute_acceleration: float = Field(ge=0)
    maximum_absolute_acceleration: float = Field(ge=0)
    p95_absolute_jerk: float = Field(ge=0)
    maximum_absolute_jerk: float = Field(ge=0)
    direction_reversals_per_second: float = Field(ge=0)
    high_frequency_energy_ratio: float = Field(ge=0)
    alternating_energy_ratio: float = Field(ge=0, le=1)


class Live2DParameterRange(DomainModel):
    minimum: float
    maximum: float
    default: float

    @model_validator(mode="after")
    def validate_range(self) -> Live2DParameterRange:
        if self.minimum >= self.maximum:
            raise ValueError("Live2D parameter range must be increasing")
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError("Live2D parameter default must be inside its range")
        return self


class Live2DDynamicThreshold(DomainModel):
    maximum_absolute_step: float = Field(gt=0)
    maximum_absolute_velocity: float = Field(gt=0)
    maximum_absolute_acceleration: float = Field(gt=0)
    maximum_absolute_jerk: float = Field(gt=0)
    maximum_direction_reversals_per_second: float = Field(gt=0)
    maximum_high_frequency_energy_ratio: float = Field(gt=0)


class Live2DGateFinding(DomainModel):
    code: NonBlankStr
    metric: NonBlankStr
    observed: float = Field(ge=0)
    threshold: float = Field(ge=0)


class Live2DParameterDiagnostics(DomainModel):
    range: Live2DParameterRange
    metrics: Live2DSignalMetrics
    threshold: Live2DDynamicThreshold
    findings: list[Live2DGateFinding] = Field(default_factory=list, max_length=32)


class Live2DMotionMetadata(DomainModel):
    file: NonBlankStr
    fps: int | None = Field(default=None, ge=1, le=120)
    fade_in_ms: float | None = Field(default=None, ge=0, le=60_000)
    fade_out_ms: float | None = Field(default=None, ge=0, le=60_000)
    frames: int | None = Field(default=None, gt=0)


class Live2DAudioCalibration(DomainModel):
    noise_floor: float = Field(ge=0, le=1)
    normalization_peak: float = Field(gt=0, le=1)


class Live2DRenderDiagnostics(DomainModel):
    schema_version: Literal["2.0"] = "2.0"
    control_mode: Literal[
        "legacy_conflict",
        "motion_only",
        "procedural_only",
        "no_lip_sync",
        "final",
    ]
    frames: int = Field(gt=0)
    envelope_frames: int = Field(gt=0)
    rendered_frames: int = Field(gt=0)
    fps: int = Field(ge=1, le=120)
    time_delta_ms_min: int = Field(gt=0)
    time_delta_ms_max: int = Field(gt=0)
    motion_group: str | None = None
    motion_restarts: int = Field(ge=0)
    motion_state_counts: dict[NonBlankStr, int] = Field(default_factory=dict)
    motion_switch_max_delta: float = Field(ge=0)
    motion_source_switch_max_delta: float = Field(ge=0)
    motion_metadata: Live2DMotionMetadata | None = None
    expression: str | None = None
    blink_events: int = Field(ge=0)
    mouth_min: float = Field(ge=0, le=1)
    mouth_p50: float = Field(ge=0, le=1)
    mouth_p95: float = Field(ge=0, le=1)
    mouth_max: float = Field(ge=0, le=1)
    mouth_max_delta: float = Field(ge=0, le=1)
    voiced_frame_ratio: float = Field(ge=0, le=1)
    exact_duplicate_pair_ratio: float = Field(ge=0, le=1)
    longest_exact_duplicate_run: int = Field(ge=0)
    controlled_parameters: list[NonBlankStr] = Field(default_factory=list, max_length=32)
    parameter_owners: dict[NonBlankStr, NonBlankStr] = Field(
        default_factory=dict,
        max_length=32,
    )
    parameter_metrics: dict[NonBlankStr, Live2DParameterDiagnostics] = Field(
        default_factory=dict,
        max_length=32,
    )
    image_metrics: dict[NonBlankStr, Live2DSignalMetrics] = Field(
        default_factory=dict,
        max_length=32,
    )
    image_thresholds: dict[NonBlankStr, float] = Field(
        default_factory=dict,
        max_length=32,
    )
    gate_findings: list[Live2DGateFinding] = Field(
        default_factory=list,
        max_length=256,
    )
    quality_gate_passed: bool
    audio_calibration: Live2DAudioCalibration
    trace_path: NonBlankStr
    trace_sha256: Sha256
    trace_size_bytes: int = Field(gt=0)

    @field_validator("trace_path")
    @classmethod
    def require_trace_local_path(cls, value: str) -> str:
        return _require_local_path(value)

    @model_validator(mode="after")
    def validate_consistency(self) -> Live2DRenderDiagnostics:
        if self.frames != self.envelope_frames or self.frames != self.rendered_frames:
            raise ValueError("Live2D diagnostic frame counts must agree")
        if self.time_delta_ms_max - self.time_delta_ms_min > 1:
            raise ValueError("Live2D user-time delta must remain frame-stable")
        if not (
            self.mouth_min
            <= self.mouth_p50
            <= self.mouth_p95
            <= self.mouth_max
        ):
            raise ValueError("Live2D mouth percentiles are inconsistent")
        if set(self.parameter_owners) != set(self.controlled_parameters):
            raise ValueError("Every controlled Live2D parameter must have one owner")
        if set(self.parameter_metrics) != set(self.controlled_parameters):
            raise ValueError("Every controlled Live2D parameter requires dynamic metrics")
        if self.quality_gate_passed != (not self.gate_findings):
            raise ValueError("Live2D quality gate state and findings disagree")
        if sum(self.motion_state_counts.values()) != self.frames:
            raise ValueError("Live2D motion state counts must cover every rendered frame")
        return self


class RenderedHostVideo(DomainModel):
    """Immutable, segment-scoped host media consumed by the video renderer.

    The Live2D SDK and model tree stay behind the host-renderer boundary.
    Remotion receives only an ordinary transparent video plus enough evidence
    to prove which role, role revision, model bytes, and audio bytes produced it.
    """

    asset_id: UUID = Field(default_factory=uuid4)
    segment_id: UUID
    speaker_id: NonBlankStr
    role_profile_id: UUID
    role_profile_version: int = Field(ge=1)
    model_sha256: Sha256
    audio_sha256: Sha256
    local_path: NonBlankStr
    sha256: Sha256
    size_bytes: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    width: int = Field(gt=0, le=4_096)
    height: int = Field(gt=0, le=4_096)
    fps: int = Field(ge=1, le=120)
    video_codec: NonBlankStr
    diagnostics: Live2DRenderDiagnostics | None = None

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class HostVisualReservations(DomainModel):
    """Typed visual snapshot kept independent from scene layout decisions."""

    renderer: Literal["placeholder", "live2d_prerender"] = "placeholder"
    host_videos: list[RenderedHostVideo] = Field(default_factory=list, max_length=100)
    live2d: Live2DReservation | None = None
    differential_art: DifferentialArtReservation | None = None

    @model_validator(mode="after")
    def validate_renderer_assets(self) -> HostVisualReservations:
        segment_ids = [asset.segment_id for asset in self.host_videos]
        asset_ids = [asset.asset_id for asset in self.host_videos]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("host videos must be unique by narration segment")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("host video asset IDs must be unique")
        if self.renderer == "placeholder" and self.host_videos:
            raise ValueError("placeholder host renderer cannot retain rendered host videos")
        if self.renderer == "live2d_prerender" and not self.host_videos:
            raise ValueError("Live2D pre-rendering requires at least one host video")
        return self


class VideoOutputProfileId(StrEnum):
    DOUYIN_VERTICAL = "douyin_vertical"
    BILIBILI_HORIZONTAL = "bilibili_horizontal"


class VideoLayout(StrEnum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


class VideoOutputProfile(DomainModel):
    """A versioned render target, kept separate from editorial semantics."""

    profile_id: VideoOutputProfileId
    width: int = Field(gt=0, le=7_680)
    height: int = Field(gt=0, le=7_680)
    fps: int = Field(default=30, ge=1, le=120)
    layout: VideoLayout

    @model_validator(mode="after")
    def validate_dimensions(self) -> VideoOutputProfile:
        if self.width % 2 or self.height % 2:
            raise ValueError("H.264 output dimensions must be even")
        if self.layout is VideoLayout.VERTICAL and self.width >= self.height:
            raise ValueError("vertical output profiles require width < height")
        if self.layout is VideoLayout.HORIZONTAL and self.width <= self.height:
            raise ValueError("horizontal output profiles require width > height")
        return self


def default_video_output_profiles() -> list[VideoOutputProfile]:
    return [
        VideoOutputProfile(
            profile_id=VideoOutputProfileId.DOUYIN_VERTICAL,
            width=1_080,
            height=1_920,
            layout=VideoLayout.VERTICAL,
        ),
        VideoOutputProfile(
            profile_id=VideoOutputProfileId.BILIBILI_HORIZONTAL,
            width=1_920,
            height=1_080,
            layout=VideoLayout.HORIZONTAL,
        ),
    ]


class EpisodeSceneModule(StrEnum):
    """Versioned semantic scene modules understood by deterministic renderers."""

    HOST_EVIDENCE = "host_evidence"
    EVIDENCE_FULLSCREEN = "evidence_fullscreen"
    SOURCE_VIDEO = "source_video"


class EpisodeHostSlot(StrEnum):
    PRIMARY = "primary"
    CORNER = "corner"


class EpisodeHostVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"


class SourceVideoAudioMode(StrEnum):
    ORIGINAL = "original"
    MUTED = "muted"


class SourceVideoPlacement(StrEnum):
    """Editorial placement policy for review-approved original media."""

    OMIT = "omit"
    AFTER_STORY = "after_story"


class ProgramStoryDirection(DomainModel):
    """Director-owned presentation decisions for one immutable story script."""

    story_id: UUID
    source_segment_ids: list[UUID] = Field(min_length=1, max_length=100)
    narration_module: EpisodeSceneModule = EpisodeSceneModule.HOST_EVIDENCE
    source_video_placement: SourceVideoPlacement = SourceVideoPlacement.OMIT

    @model_validator(mode="after")
    def validate_story_direction(self) -> ProgramStoryDirection:
        if len(self.source_segment_ids) != len(set(self.source_segment_ids)):
            raise ValueError("program story source segment IDs must be unique")
        if self.narration_module is EpisodeSceneModule.SOURCE_VIDEO:
            raise ValueError("story narration cannot use the source_video scene module")
        return self


class ProgramBridge(DomainModel):
    """Identity and adjacency proof for one generated transition utterance."""

    from_story_id: UUID
    to_story_id: UUID
    segment_id: UUID

    @model_validator(mode="after")
    def reject_self_bridge(self) -> ProgramBridge:
        if self.from_story_id == self.to_story_id:
            raise ValueError("program bridges must connect two different stories")
        return self


class ProgramDirectorPlan(DomainModel):
    """Strict editorial IR produced by AI and executed deterministically.

    The model may order stories and choose registered presentation policies,
    but it never emits frame numbers, filesystem paths, or renderer options.
    Source story segments remain identifiable and bridges are explicit new
    utterances, so editorial review can distinguish facts from connective copy.
    """

    schema_version: Literal["1.0"] = "1.0"
    story_order: list[UUID] = Field(min_length=1, max_length=15)
    stories: list[ProgramStoryDirection] = Field(min_length=1, max_length=15)
    bridges: list[ProgramBridge] = Field(default_factory=list, max_length=14)

    @model_validator(mode="after")
    def validate_program_structure(self) -> ProgramDirectorPlan:
        if len(self.story_order) != len(set(self.story_order)):
            raise ValueError("program director story_order must contain unique IDs")
        if [story.story_id for story in self.stories] != self.story_order:
            raise ValueError("program story directions must follow story_order exactly")
        expected_edges = list(zip(self.story_order, self.story_order[1:], strict=False))
        actual_edges = [
            (bridge.from_story_id, bridge.to_story_id) for bridge in self.bridges
        ]
        if actual_edges != expected_edges:
            raise ValueError("program bridges must cover each adjacent story pair exactly once")
        segment_ids = self.narration_segment_ids()
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("program narration segment IDs must be globally unique")
        return self

    def narration_segment_ids(self) -> list[UUID]:
        bridges_by_source = {bridge.from_story_id: bridge for bridge in self.bridges}
        ordered: list[UUID] = []
        for story in self.stories:
            ordered.extend(story.source_segment_ids)
            bridge = bridges_by_source.get(story.story_id)
            if bridge is not None:
                ordered.append(bridge.segment_id)
        return ordered


class DirectedProgramDraft(DomainModel):
    """Validated result returned by a replaceable program-director adapter."""

    direction: ProgramDirectorPlan
    script: ScriptDocument

    @model_validator(mode="after")
    def validate_script_identity(self) -> DirectedProgramDraft:
        if self.direction.narration_segment_ids() != [
            segment.segment_id for segment in self.script.segments
        ]:
            raise ValueError("directed script must follow the program narration identity")
        return self


class SourceVideoRenderAsset(DomainModel):
    """Immutable, review-approved source video exposed to the episode compiler."""

    asset_id: UUID
    story_id: UUID
    transcription_id: UUID
    transcription_version: int = Field(ge=2)
    transcription_review: TranscriptReview
    local_path: NonBlankStr
    sha256: Sha256
    size_bytes: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    in_ms: int = Field(default=0, ge=0)
    out_ms: int = Field(gt=0)
    audio_mode: SourceVideoAudioMode = SourceVideoAudioMode.ORIGINAL
    source_label: NonBlankStr
    captions: list[TimedCaptionCue] = Field(min_length=1, max_length=10_000)

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)

    @model_validator(mode="after")
    def validate_reviewed_range(self) -> SourceVideoRenderAsset:
        if self.out_ms <= self.in_ms or self.out_ms > self.duration_ms:
            raise ValueError("source video selection must stay inside the verified media duration")
        review = self.transcription_review
        if (
            review.decision is not TranscriptReviewDecision.APPROVE
            or self.transcription_version != review.reviewed_version + 1
        ):
            raise ValueError("source videos require the final approved transcription version")
        if self.captions[-1].end_ms > self.duration_ms + 2_000:
            raise ValueError("source video captions extend beyond the verified media duration")
        return self


class EpisodeScene(DomainModel):
    scene_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=0, le=99)
    module_id: EpisodeSceneModule
    narration_segment_id: UUID | None = None
    source_video_asset_id: UUID | None = None
    speaker_id: NonBlankStr | None = None
    host_visibility: EpisodeHostVisibility
    host_slot: EpisodeHostSlot | None = None
    host_enter: bool = False
    host_exit: bool = False
    transition_type: SceneTransition = SceneTransition.BLACK
    variant_id: SceneVariantId | None = None
    visual_asset_ids: list[UUID] = Field(default_factory=list, max_length=12)
    primary_visual_asset_id: UUID | None = None

    @model_validator(mode="after")
    def validate_module_capabilities(self) -> EpisodeScene:
        if self.host_visibility is EpisodeHostVisibility.VISIBLE and self.host_slot is None:
            raise ValueError("visible episode hosts require a semantic slot")
        if self.host_visibility is EpisodeHostVisibility.HIDDEN and self.host_slot is not None:
            raise ValueError("hidden episode hosts cannot reserve a visual slot")
        if (
            self.module_id is EpisodeSceneModule.HOST_EVIDENCE
            and self.host_visibility is not EpisodeHostVisibility.VISIBLE
        ):
            raise ValueError("host_evidence scenes require a visible host")
        if (
            self.module_id is EpisodeSceneModule.EVIDENCE_FULLSCREEN
            and self.host_visibility is not EpisodeHostVisibility.HIDDEN
        ):
            raise ValueError("evidence_fullscreen scenes require the host to leave the frame")
        if self.module_id is EpisodeSceneModule.SOURCE_VIDEO:
            if self.host_visibility is not EpisodeHostVisibility.HIDDEN:
                raise ValueError("source_video scenes require the host to leave the frame")
            if self.narration_segment_id is not None or self.source_video_asset_id is None:
                raise ValueError("source_video scenes require only a source video asset")
            if self.speaker_id is not None:
                raise ValueError("source_video scenes cannot claim a narration speaker")
        elif (
            self.narration_segment_id is None
            or self.source_video_asset_id is not None
            or self.speaker_id is None
        ):
            raise ValueError("narration scenes require one segment and one speaker")
        if len(self.visual_asset_ids) != len(set(self.visual_asset_ids)):
            raise ValueError("scene visual asset IDs must be unique")
        if (
            self.primary_visual_asset_id is not None
            and self.primary_visual_asset_id not in self.visual_asset_ids
        ):
            raise ValueError("primary visual asset must belong to the scene visual asset set")
        if self.module_id is EpisodeSceneModule.SOURCE_VIDEO and self.visual_asset_ids:
            raise ValueError("source_video scenes use their typed source video asset only")
        return self


class EpisodePlan(DomainModel):
    """Editorial semantics between reviewed narration and low-level render frames."""

    schema_version: Literal["1.0"] = "1.0"
    batch_id: UUID
    scenes: list[EpisodeScene] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_scene_sequence(self) -> EpisodePlan:
        if [scene.sequence for scene in self.scenes] != list(range(len(self.scenes))):
            raise ValueError("episode scene sequence must be contiguous and zero-based")
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("episode scene IDs must be unique")
        segment_ids = [
            scene.narration_segment_id
            for scene in self.scenes
            if scene.narration_segment_id is not None
        ]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("each narration segment must belong to exactly one episode scene")
        return self


class TemplateAssetRequirement(DomainModel):
    asset_type: VisualAssetType
    required: bool = True
    minimum: int = Field(default=1, ge=0, le=12)
    maximum: int = Field(default=1, ge=1, le=12)

    @model_validator(mode="after")
    def validate_range(self) -> TemplateAssetRequirement:
        if self.minimum > self.maximum:
            raise ValueError("template asset requirement minimum cannot exceed maximum")
        if self.required and self.minimum == 0:
            raise ValueError("required template assets must require at least one item")
        return self


class SceneVariantDefinition(DomainModel):
    variant_id: SceneVariantId
    module_id: EpisodeSceneModule
    display_name: NonBlankStr
    supported_profiles: list[VideoOutputProfileId] = Field(min_length=1, max_length=8)
    supported_host_slots: list[EpisodeHostSlot] = Field(default_factory=list, max_length=8)
    asset_requirements: list[TemplateAssetRequirement] = Field(
        default_factory=list,
        max_length=12,
    )
    minimum_visual_assets: int = Field(default=0, ge=0, le=12)
    maximum_visual_assets: int = Field(default=12, ge=0, le=12)

    @model_validator(mode="after")
    def validate_unique_capabilities(self) -> SceneVariantDefinition:
        if len(self.supported_profiles) != len(set(self.supported_profiles)):
            raise ValueError("scene variant profile IDs must be unique")
        if len(self.supported_host_slots) != len(set(self.supported_host_slots)):
            raise ValueError("scene variant host slots must be unique")
        asset_types = [requirement.asset_type for requirement in self.asset_requirements]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("scene variant asset requirements must be unique by type")
        if self.minimum_visual_assets > self.maximum_visual_assets:
            raise ValueError("scene variant visual asset range is invalid")
        return self


class OutputProfileLayout(DomainModel):
    profile_id: VideoOutputProfileId
    safe_area_top: float = Field(ge=0, le=0.25)
    safe_area_right: float = Field(ge=0, le=0.25)
    safe_area_bottom: float = Field(ge=0, le=0.35)
    safe_area_left: float = Field(ge=0, le=0.25)
    host_primary_width: float = Field(gt=0, le=0.8)
    host_corner_width: float = Field(gt=0, le=0.6)
    caption_max_width: float = Field(gt=0, le=1)
    media_fit: Literal["contain", "cover"] = "cover"


class LayoutPreset(DomainModel):
    preset_id: NonBlankStr
    profiles: list[OutputProfileLayout] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_profiles(self) -> LayoutPreset:
        ids = [profile.profile_id for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("layout preset output profile IDs must be unique")
        return self


class DesignTokens(DomainModel):
    font_family: NonBlankStr = 'Inter, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif'
    title_font_family: NonBlankStr = 'Inter, "Noto Sans CJK SC", sans-serif'
    body_font_family: NonBlankStr = 'Inter, "Noto Sans CJK SC", sans-serif'
    caption_font_family: NonBlankStr = 'Inter, "Noto Sans CJK SC", sans-serif'
    mono_font_family: NonBlankStr = '"IBM Plex Mono", Consolas, monospace'
    background: HexColor = "#101512"
    foreground: HexColor = "#f3f1e8"
    accent: HexColor = "#85a77d"
    signal: HexColor = "#e4a853"
    panel: HexColor = "#182019"
    muted: HexColor = "#a8b4a8"
    title_scale: float = Field(default=1.0, ge=0.5, le=2)
    body_scale: float = Field(default=1.0, ge=0.5, le=2)
    caption_scale: float = Field(default=1.0, ge=0.5, le=2)
    title_weight: int = Field(default=760, ge=100, le=900)
    body_weight: int = Field(default=500, ge=100, le=900)
    caption_weight: int = Field(default=650, ge=100, le=900)
    line_height: float = Field(default=1.32, ge=0.9, le=2)
    corner_radius: int = Field(default=30, ge=0, le=120)
    border_width: int = Field(default=2, ge=0, le=12)
    shadow_blur: int = Field(default=48, ge=0, le=160)
    panel_opacity: float = Field(default=0.88, ge=0, le=1)
    spacing_unit: int = Field(default=8, ge=2, le=32)
    caption_max_lines: int = Field(default=2, ge=1, le=4)
    animation_speed: float = Field(default=1.0, ge=0.25, le=3)
    animation_easing: NonBlankStr = "ease-out"
    image_zoom_min: float = Field(default=1.0, ge=0.5, le=2)
    image_zoom_max: float = Field(default=1.04, ge=0.5, le=2)

    @model_validator(mode="after")
    def validate_image_zoom(self) -> DesignTokens:
        if self.image_zoom_max < self.image_zoom_min:
            raise ValueError("image zoom maximum cannot be below its minimum")
        return self


class TemplateCapabilities(DomainModel):
    supported_profiles: list[VideoOutputProfileId] = Field(min_length=1, max_length=8)
    supported_modules: list[EpisodeSceneModule] = Field(min_length=1, max_length=32)
    supports_bilingual_captions: bool = True
    supports_live2d: bool = True
    supports_source_attribution: bool = True

    @model_validator(mode="after")
    def validate_unique_values(self) -> TemplateCapabilities:
        if len(self.supported_profiles) != len(set(self.supported_profiles)):
            raise ValueError("template capability profile IDs must be unique")
        if len(self.supported_modules) != len(set(self.supported_modules)):
            raise ValueError("template capability module IDs must be unique")
        return self


class TemplateDefinition(DomainModel):
    template_id: TemplateId
    template_version: TemplateVersion
    display_name: NonBlankStr
    capabilities: TemplateCapabilities
    scene_variants: list[SceneVariantDefinition] = Field(min_length=1, max_length=64)
    default_scene_variants: dict[EpisodeSceneModule, SceneVariantId]
    layout_preset: LayoutPreset
    design_tokens: DesignTokens
    intro_variant: NonBlankStr
    outro_variant: NonBlankStr
    transition_pack: NonBlankStr
    caption_preset: NonBlankStr
    source_bar_preset: NonBlankStr
    host_preset: NonBlankStr
    static_asset_requirements: list[NonBlankStr] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_template_references(self) -> TemplateDefinition:
        variant_ids = [variant.variant_id for variant in self.scene_variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise ValueError("template scene variant IDs must be unique")
        variants = {variant.variant_id: variant for variant in self.scene_variants}
        if set(self.default_scene_variants) != set(self.capabilities.supported_modules):
            raise ValueError("template defaults must cover every supported scene module")
        for module_id, variant_id in self.default_scene_variants.items():
            variant = variants.get(variant_id)
            if variant is None or variant.module_id is not module_id:
                raise ValueError("template default scene variant reference is invalid")
        layout_profiles = {profile.profile_id for profile in self.layout_preset.profiles}
        if layout_profiles != set(self.capabilities.supported_profiles):
            raise ValueError("template layout profiles must match template capabilities")
        for variant in self.scene_variants:
            if variant.module_id not in self.capabilities.supported_modules:
                raise ValueError("template scene variant uses an unsupported module")
            if not set(variant.supported_profiles).issubset(
                self.capabilities.supported_profiles
            ):
                raise ValueError("template scene variant uses an unsupported output profile")
        return self


class RemotionVideoProps(DomainModel):
    """Backend-owned subset of ``video/src/schema.ts``.

    This object is deliberately absent until program narration has been manually
    synthesized. It therefore cannot accidentally encode an unreviewed or
    source-story-flat render plan.
    """

    manifest: ProductionManifest
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    intro_duration_ms: int = Field(default=700, ge=0, le=5_000)
    # Zero preserves the exact hash semantics of pre-outro persisted snapshots.
    # New application-created batches explicitly opt into the current default.
    outro_duration_ms: int = Field(default=0, ge=0, le=10_000)
    transition_duration_ms: int = Field(default=180, ge=0, le=2_000)
    theme: VideoTheme = Field(default_factory=VideoTheme)
    bgm: BgmRenderSpec | None = None
    visual_reservations: HostVisualReservations = Field(default_factory=HostVisualReservations)
    episode_plan: EpisodePlan | None = None
    source_videos: list[SourceVideoRenderAsset] = Field(default_factory=list, max_length=100)
    visual_assets: list[VisualRenderAsset] = Field(default_factory=list, max_length=1_200)
    template: TemplateDefinition | None = None
    output_profiles: list[VideoOutputProfile] = Field(
        default_factory=default_video_output_profiles,
        min_length=2,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_output_profiles(self) -> RemotionVideoProps:
        profile_ids = [profile.profile_id for profile in self.output_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("output profile IDs must be unique")
        required = {
            VideoOutputProfileId.DOUYIN_VERTICAL,
            VideoOutputProfileId.BILIBILI_HORIZONTAL,
        }
        if not required.issubset(profile_ids):
            raise ValueError("Douyin and Bilibili output profiles are required")
        if self.episode_plan is not None:
            if self.episode_plan.batch_id != self.manifest.story_id:
                raise ValueError("episode plan must be owned by the rendered batch")
            if [
                scene.narration_segment_id
                for scene in self.episode_plan.scenes
                if scene.narration_segment_id is not None
            ] != [
                segment.segment_id for segment in self.manifest.timeline
            ]:
                raise ValueError("episode scenes must cover the manifest timeline in order")
            narration_scenes = [
                scene
                for scene in self.episode_plan.scenes
                if scene.narration_segment_id is not None
            ]
            for scene, segment in zip(
                narration_scenes,
                self.manifest.timeline,
                strict=True,
            ):
                if (
                    scene.speaker_id != segment.speaker_id
                    or scene.transition_type != segment.scene_transition
                ):
                    raise ValueError(
                        "episode scene speaker and transition must match reviewed narration"
                    )
            asset_ids = [asset.asset_id for asset in self.source_videos]
            if len(asset_ids) != len(set(asset_ids)):
                raise ValueError("source video asset IDs must be unique")
            referenced_asset_ids = {
                scene.source_video_asset_id
                for scene in self.episode_plan.scenes
                if scene.source_video_asset_id is not None
            }
            if referenced_asset_ids != set(asset_ids):
                raise ValueError("episode source video scenes must match the approved asset set")
            visual_asset_ids = [asset.asset_id for asset in self.visual_assets]
            if len(visual_asset_ids) != len(set(visual_asset_ids)):
                raise ValueError("render visual asset IDs must be unique")
            referenced_visual_ids = {
                visual_id
                for scene in self.episode_plan.scenes
                for visual_id in scene.visual_asset_ids
            }
            if not referenced_visual_ids.issubset(visual_asset_ids):
                raise ValueError("episode scenes reference unknown visual assets")
            if self.template is not None:
                if not {
                    profile.profile_id for profile in self.output_profiles
                }.issubset(self.template.capabilities.supported_profiles):
                    raise ValueError("output profiles exceed the selected template capabilities")
                variants = {
                    variant.variant_id: variant for variant in self.template.scene_variants
                }
                visual_by_id = {asset.asset_id: asset for asset in self.visual_assets}
                for scene in self.episode_plan.scenes:
                    if scene.module_id not in self.template.capabilities.supported_modules:
                        raise ValueError("episode scene is unsupported by the selected template")
                    variant_id = (
                        scene.variant_id
                        or self.template.default_scene_variants[scene.module_id]
                    )
                    variant = variants.get(variant_id)
                    if variant is None or variant.module_id is not scene.module_id:
                        raise ValueError("episode scene references an invalid template variant")
                    if not (
                        variant.minimum_visual_assets
                        <= len(scene.visual_asset_ids)
                        <= variant.maximum_visual_assets
                    ):
                        raise ValueError("episode scene violates template visual asset count")
                    counts: dict[VisualAssetType, int] = {}
                    for visual_id in scene.visual_asset_ids:
                        asset = visual_by_id[visual_id]
                        counts[asset.asset_type] = counts.get(asset.asset_type, 0) + 1
                    for requirement in variant.asset_requirements:
                        count = counts.get(requirement.asset_type, 0)
                        if count < requirement.minimum or count > requirement.maximum:
                            raise ValueError("episode scene violates template asset requirements")
        elif self.source_videos:
            raise ValueError("source video assets require a typed episode plan")
        elif self.visual_assets:
            raise ValueError("visual assets require a typed episode plan")
        if self.visual_reservations.renderer == "live2d_prerender":
            hosts_by_segment = {
                asset.segment_id: asset
                for asset in self.visual_reservations.host_videos
            }
            if list(hosts_by_segment) != [segment.segment_id for segment in self.manifest.timeline]:
                raise ValueError(
                    "pre-rendered host videos must cover the manifest timeline in order"
                )
            for segment in self.manifest.timeline:
                host = hosts_by_segment[segment.segment_id]
                if (
                    host.speaker_id != segment.speaker_id
                    or host.duration_ms != segment.end_ms - segment.start_ms
                ):
                    raise ValueError(
                        "pre-rendered host identity and duration must match narration"
                    )
        return self


class VideoBatchStory(DomainModel):
    """Immutable source-story evidence for one directed program.

    ``source_manifest`` remains point-in-time timing evidence. The director may
    reorder the story, but the compiled program reuses its reviewed script
    segment identities instead of asking a model to paraphrase the facts.
    """

    sequence: int = Field(ge=0, le=14)
    story_id: UUID
    story_version: int = Field(ge=1)
    category: ContentCategory
    title: NonBlankStr
    script: ScriptDocument
    script_sha256: Sha256
    source_manifest: ProductionManifest
    source_manifest_sha256: Sha256
    visual_assets: list[VisualRenderAsset] = Field(default_factory=list, max_length=120)
    reserved_at: datetime = Field(default_factory=utc_now)
    used_at: datetime | None = None

    @field_validator("reserved_at", "used_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_source_snapshot(self) -> VideoBatchStory:
        if self.source_manifest.story_id != self.story_id:
            raise ValueError("source manifest ID must match story_id")
        if self.source_manifest.script_revision != self.script.revision:
            raise ValueError("source manifest revision must match source script revision")
        if self.source_manifest.spoken_language != self.script.spoken_language:
            raise ValueError("source manifest language must match source script language")
        if self.script_sha256 != model_sha256(self.script):
            raise ValueError("script_sha256 does not match source script")
        if self.source_manifest_sha256 != model_sha256(self.source_manifest):
            raise ValueError("source_manifest_sha256 does not match source manifest")
        for asset in self.visual_assets:
            if asset.story_id != self.story_id:
                raise ValueError("visual asset snapshot belongs to another story")
            if asset.segment_id is not None and asset.segment_id not in {
                segment.segment_id for segment in self.script.segments
            }:
                raise ValueError("visual asset snapshot references an unknown script segment")

        source_segments = self.source_manifest.timeline
        script_segments = self.script.segments
        if len(source_segments) != len(script_segments):
            raise ValueError("source manifest must contain every source script segment")
        cursor = 0
        for index, (timeline, script) in enumerate(
            zip(source_segments, script_segments, strict=True)
        ):
            if (
                timeline.sequence != index
                or timeline.start_ms != cursor
                or timeline.end_ms <= cursor
                or timeline.segment_id != script.segment_id
                or timeline.spoken_text != script.spoken_text
                or timeline.spoken_language != script.spoken_language
                or timeline.captions != script.captions
                or timeline.speaker_id != script.speaker_id
                or timeline.emotion != script.emotion
                or timeline.scene_transition != script.scene_transition
                or timeline.visual_hint != script.visual_hint
            ):
                raise ValueError("source manifest does not faithfully describe its source script")
            cursor = timeline.end_ms
        if cursor != self.source_manifest.total_duration_ms:
            raise ValueError("source manifest timeline must end at total_duration_ms")
        return self


class BatchNarrationSourceEvidence(DomainModel):
    """Stable source provenance consumed by a program director."""

    story_id: UUID
    story_version: int = Field(ge=1)
    script_revision: int = Field(ge=1)
    script_sha256: Sha256
    source_manifest_sha256: Sha256


def narration_source_evidence_sha256(
    evidence: list[BatchNarrationSourceEvidence],
) -> str:
    return _canonical_sha256([item.model_dump(mode="json") for item in evidence])


class BatchNarrationArtifact(DomainModel):
    """The reviewable program narration and its optional synthesized media."""

    source_evidence: list[BatchNarrationSourceEvidence] = Field(min_length=1, max_length=15)
    source_evidence_sha256: Sha256
    script: ScriptDocument
    direction: ProgramDirectorPlan | None = None
    audio: AudioBundle | None = None
    manifest: ProductionManifest | None = None
    composed_at: datetime = Field(default_factory=utc_now)
    synthesized_at: datetime | None = None

    @field_validator("composed_at", "synthesized_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_artifact_shape(self) -> BatchNarrationArtifact:
        ids = [item.story_id for item in self.source_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("batch narration source evidence must have unique story IDs")
        if self.source_evidence_sha256 != narration_source_evidence_sha256(self.source_evidence):
            raise ValueError("source_evidence_sha256 does not match source evidence")
        if self.direction is not None and self.direction.narration_segment_ids() != [
            segment.segment_id for segment in self.script.segments
        ]:
            raise ValueError("program direction must cover the narration script in order")
        if (self.audio is None) != (self.manifest is None):
            raise ValueError("batch narration audio and manifest must appear together")
        if self.audio is None and self.synthesized_at is not None:
            raise ValueError("unsynthesized batch narration cannot have synthesized_at")
        if self.audio is not None and self.synthesized_at is None:
            raise ValueError("synthesized batch narration requires synthesized_at")
        return self


class NarrationReview(DomainModel):
    reviewer_id: NonBlankStr
    decision: NarrationReviewDecision
    reviewed_batch_version: int = Field(ge=1)
    script_revision: int = Field(ge=1)
    script_sha256: Sha256
    note: str | None = None
    reviewed_at: datetime = Field(default_factory=utc_now)

    @field_validator("reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class TimelineReview(DomainModel):
    reviewer_id: NonBlankStr
    decision: TimelineReviewDecision
    reviewed_batch_version: int = Field(ge=1)
    story_order: list[UUID] = Field(min_length=1, max_length=15)
    render_input_sha256: Sha256 | None = None
    note: str | None = None
    reviewed_at: datetime = Field(default_factory=utc_now)

    @field_validator("reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_unique_order(self) -> TimelineReview:
        if len(self.story_order) != len(set(self.story_order)):
            raise ValueError("reviewed story_order must contain unique IDs")
        return self


class VideoVisualQualityDiagnostics(DomainModel):
    black_segment_count: int = Field(ge=0)
    longest_black_duration_seconds: float = Field(ge=0)
    freeze_segment_count: int = Field(ge=0)
    longest_freeze_duration_seconds: float = Field(ge=0)
    expected_duration_seconds: float | None = Field(default=None, gt=0)
    container_duration_seconds: float | None = Field(default=None, gt=0)
    audio_duration_seconds: float | None = Field(default=None, gt=0)
    duration_delta_seconds: float | None = Field(default=None, ge=0)
    gate_version: Literal["1.0", "1.1"] = "1.0"


class VideoRenderOutput(DomainModel):
    profile_id: VideoOutputProfileId
    local_path: NonBlankStr
    size_bytes: int = Field(gt=0)
    sha256: Sha256
    width: int = Field(gt=0, le=7_680)
    height: int = Field(gt=0, le=7_680)
    fps: int = Field(ge=1, le=120)
    duration_in_frames: int = Field(gt=0)
    video_codec: NonBlankStr
    audio_codec: NonBlankStr
    visual_quality: VideoVisualQualityDiagnostics | None = None

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)


class LegacyVideoRenderArtifact(DomainModel):
    """Read-only compatibility evidence for pre dual-output rendered batches.

    Existing rendered batches hold durable story claims and cannot safely be
    recreated.  Keeping their original shape readable is therefore an audit
    requirement, not an invitation to produce new single-output artifacts.
    """

    local_path: NonBlankStr
    size_bytes: int = Field(gt=0)
    sha256: Sha256
    renderer: NonBlankStr
    rendered_at: datetime = Field(default_factory=utc_now)

    @field_validator("local_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        return _require_local_path(value)

    @field_validator("rendered_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class VideoRenderArtifact(DomainModel):
    """Atomic evidence for every required output of one semantic render snapshot."""

    renderer: NonBlankStr
    outputs: list[VideoRenderOutput] = Field(min_length=2, max_length=8)
    rendered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_outputs(self) -> VideoRenderArtifact:
        profile_ids = [output.profile_id for output in self.outputs]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("render output profile IDs must be unique")
        required = {
            VideoOutputProfileId.DOUYIN_VERTICAL,
            VideoOutputProfileId.BILIBILI_HORIZONTAL,
        }
        if not required.issubset(profile_ids):
            raise ValueError("render artifact is missing a required output profile")
        return self

    @field_validator("rendered_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class VideoRenderFailure(DomainModel):
    message: NonBlankStr
    retryable: bool = True
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class BatchNarrationFailure(DomainModel):
    message: NonBlankStr
    retryable: bool = True
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class VideoBatch(DomainModel):
    batch_id: UUID = Field(default_factory=uuid4)
    status: VideoBatchStatus = VideoBatchStatus.PENDING_NARRATION_REVIEW
    title: NonBlankStr
    subtitle: str | None = None
    template: TemplateDefinition | None = None
    stories: list[VideoBatchStory] = Field(min_length=1, max_length=15)
    narration: BatchNarrationArtifact
    bgm: BgmSelection | None = None
    visual_reservations: HostVisualReservations = Field(default_factory=HostVisualReservations)
    remotion_props: RemotionVideoProps | None = None
    input_assets: list[VideoInputAsset] = Field(default_factory=list, max_length=1_301)
    render_input_sha256: Sha256 | None = None
    narration_reviews: list[NarrationReview] = Field(default_factory=list, max_length=100)
    timeline_review: TimelineReview | None = None
    artifact: VideoRenderArtifact | LegacyVideoRenderArtifact | None = None
    narration_failure: BatchNarrationFailure | None = None
    last_failure: VideoRenderFailure | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_batch(self) -> VideoBatch:
        story_ids = [story.story_id for story in self.stories]
        if len(story_ids) != len(set(story_ids)):
            raise ValueError("batch story IDs must be unique")
        if [story.sequence for story in self.stories] != list(range(len(self.stories))):
            raise ValueError("batch story sequence must be contiguous and zero-based")

        expected_evidence = [
            BatchNarrationSourceEvidence(
                story_id=story.story_id,
                story_version=story.story_version,
                script_revision=story.script.revision,
                script_sha256=story.script_sha256,
                source_manifest_sha256=story.source_manifest_sha256,
            )
            for story in self.stories
        ]
        if self.narration.source_evidence != expected_evidence:
            raise ValueError("batch narration source evidence must match source-story snapshots")
        if self.narration.direction is not None:
            direction = self.narration.direction
            if direction.story_order != story_ids:
                raise ValueError("program director order must match immutable batch story order")
            source_segments = {
                story.story_id: [segment.segment_id for segment in story.script.segments]
                for story in self.stories
            }
            for story_direction in direction.stories:
                if source_segments.get(story_direction.story_id) != (
                    story_direction.source_segment_ids
                ):
                    raise ValueError(
                        "program direction must preserve each source story segment identity"
                    )

        generated = self.narration.audio is not None
        if generated:
            self._validate_synthesized_narration()
        elif (
            self.remotion_props is not None
            or self.input_assets
            or self.render_input_sha256 is not None
        ):
            raise ValueError("unsynthesized batch narration cannot expose Remotion props or assets")

        self._validate_review_evidence(story_ids, generated)
        self._validate_render_evidence(generated)
        return self

    def _validate_synthesized_narration(self) -> None:
        assert self.narration.audio is not None
        assert self.narration.manifest is not None
        assert self.remotion_props is not None
        assert self.render_input_sha256 is not None

        script = self.narration.script
        audio = self.narration.audio
        manifest = self.narration.manifest
        script_ids = {segment.segment_id for segment in script.segments}
        clips = {clip.segment_id: clip for clip in audio.clips}
        if audio.revision != script.revision or set(clips) != script_ids:
            raise ValueError(
                "batch narration audio revision or segment IDs do not match its script"
            )
        if (
            manifest.story_id != self.batch_id
            or manifest.script_revision != script.revision
            or manifest.spoken_language != script.spoken_language
            or len(manifest.timeline) != len(script.segments)
        ):
            raise ValueError("merged production manifest does not match batch narration identity")
        cursor = 0
        for index, (timeline, segment) in enumerate(
            zip(manifest.timeline, script.segments, strict=True)
        ):
            clip = clips.get(segment.segment_id)
            if clip is None:
                raise ValueError("merged production manifest references a missing batch audio clip")
            if (
                timeline.sequence != index
                or timeline.start_ms != cursor
                or timeline.end_ms != cursor + clip.duration_ms
                or timeline.segment_id != segment.segment_id
                or timeline.spoken_text != segment.spoken_text
                or timeline.spoken_language != segment.spoken_language
                or timeline.captions != segment.captions
                or timeline.speaker_id != segment.speaker_id
                or timeline.emotion != segment.emotion
                or timeline.scene_transition != segment.scene_transition
                or timeline.visual_hint != segment.visual_hint
                or timeline.audio_path != clip.path
            ):
                raise ValueError(
                    "merged production manifest must be built from batch script and clips"
                )
            cursor = timeline.end_ms
        if manifest.total_duration_ms != cursor:
            raise ValueError("merged production manifest timeline must end at total_duration_ms")
        if self.remotion_props.manifest != manifest:
            raise ValueError("Remotion props must use the merged batch manifest")
        if self.remotion_props.title != self.title or self.remotion_props.subtitle != self.subtitle:
            raise ValueError("Remotion title metadata must match the batch")
        if self.remotion_props.visual_reservations != self.visual_reservations:
            raise ValueError("Remotion visual reservations must match the batch snapshot")
        hosts_by_segment = {
            asset.segment_id: asset
            for asset in self.visual_reservations.host_videos
        }
        for segment_id, host in hosts_by_segment.items():
            clip = clips.get(segment_id)
            if clip is None or host.audio_sha256 != clip.sha256:
                raise ValueError("pre-rendered host audio evidence must match batch TTS")
        expected_bgm = self.bgm.render_spec() if self.bgm is not None else None
        if self.remotion_props.bgm != expected_bgm:
            raise ValueError("Remotion BGM spec must match the selected catalog track")

        asset_keys = [(asset.kind, asset.local_path) for asset in self.input_assets]
        if len(asset_keys) != len(set(asset_keys)):
            raise ValueError("video input assets must not repeat a kind/path pair")
        recorded_audio_paths = {
            asset.local_path
            for asset in self.input_assets
            if asset.kind is VideoInputAssetKind.AUDIO
        }
        manifest_audio_paths = {segment.audio_path for segment in manifest.timeline}
        if recorded_audio_paths != manifest_audio_paths:
            raise ValueError("video input audio evidence must match merged narration clips")
        bgm_assets = [asset for asset in self.input_assets if asset.kind is VideoInputAssetKind.BGM]
        if expected_bgm is None:
            if bgm_assets:
                raise ValueError("batches without BGM cannot retain BGM input evidence")
        elif len(bgm_assets) != 1 or bgm_assets[0].local_path != expected_bgm.local_path:
            raise ValueError("BGM input evidence must match the selected BGM path")
        recorded_source_video_paths = {
            asset.local_path
            for asset in self.input_assets
            if asset.kind is VideoInputAssetKind.SOURCE_VIDEO
        }
        expected_source_video_paths = {
            asset.local_path for asset in self.remotion_props.source_videos
        }
        recorded_host_video_paths = {
            asset.local_path
            for asset in self.input_assets
            if asset.kind is VideoInputAssetKind.HOST_VIDEO
        }
        expected_host_video_paths = {
            asset.local_path for asset in self.visual_reservations.host_videos
        }
        if recorded_host_video_paths != expected_host_video_paths:
            raise ValueError("host video input evidence must match visual reservations")
        if recorded_source_video_paths != expected_source_video_paths:
            raise ValueError("source video input evidence must match approved render assets")
        if self.render_input_sha256 != render_input_sha256(self.remotion_props, self.input_assets):
            raise ValueError("render_input_sha256 does not match props and input assets")

    def _validate_review_evidence(self, story_ids: list[UUID], generated: bool) -> None:
        if self.timeline_review is not None and self.timeline_review.story_order != story_ids:
            raise ValueError("timeline review order must match the immutable batch order")
        if (
            self.timeline_review is not None
            and self.timeline_review.render_input_sha256 != self.render_input_sha256
        ):
            raise ValueError("timeline review must bind the exact render input snapshot")
        latest_narration = self.narration_reviews[-1] if self.narration_reviews else None

        pre_tts_states = {
            VideoBatchStatus.PENDING_NARRATION_REVIEW,
            VideoBatchStatus.PENDING_BATCH_TTS,
            VideoBatchStatus.PROCESSING_BATCH_TTS,
        }
        synthesized_states = {
            VideoBatchStatus.PENDING_TIMELINE_REVIEW,
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.RENDERING,
            VideoBatchStatus.RENDERED,
            VideoBatchStatus.FAILED,
        }
        if self.status in pre_tts_states and generated:
            raise ValueError("pre-TTS batch states cannot retain synthesized narration")
        if self.status in synthesized_states and not generated:
            raise ValueError("post-TTS batch states require synthesized narration")

        if self.status is VideoBatchStatus.PENDING_NARRATION_REVIEW:
            if self.timeline_review is not None:
                raise ValueError("narration review cannot retain timeline review evidence")
            if (
                latest_narration is not None
                and latest_narration.decision is NarrationReviewDecision.APPROVE
            ):
                raise ValueError("approved narration must advance to the manual TTS gate")
        elif self.status in {
            VideoBatchStatus.PENDING_BATCH_TTS,
            VideoBatchStatus.PROCESSING_BATCH_TTS,
        }:
            if self.timeline_review is not None:
                raise ValueError("manual batch TTS gate cannot retain timeline review evidence")
            if (
                latest_narration is None
                or latest_narration.decision is not NarrationReviewDecision.APPROVE
            ):
                raise ValueError("manual batch TTS requires approved narration review evidence")
        elif self.status is VideoBatchStatus.PENDING_TIMELINE_REVIEW:
            if self.timeline_review is not None:
                raise ValueError("pending timeline review cannot already contain a timeline review")
            if (
                latest_narration is None
                or latest_narration.decision is not NarrationReviewDecision.APPROVE
            ):
                raise ValueError("timeline review requires approved narration review evidence")
        elif self.status in {
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.RENDERING,
            VideoBatchStatus.RENDERED,
            VideoBatchStatus.FAILED,
        }:
            if (
                latest_narration is None
                or latest_narration.decision is not NarrationReviewDecision.APPROVE
            ):
                raise ValueError("renderable batch requires approved narration review evidence")
            if (
                self.timeline_review is None
                or self.timeline_review.decision is not TimelineReviewDecision.APPROVE
            ):
                raise ValueError("renderable batches require an approved timeline review")
        elif self.status is VideoBatchStatus.REJECTED:
            narrative_rejected = (
                self.timeline_review is None
                and latest_narration is not None
                and latest_narration.decision is NarrationReviewDecision.REJECT
                and not generated
            )
            timeline_rejected = (
                self.timeline_review is not None
                and self.timeline_review.decision is TimelineReviewDecision.REJECT
                and generated
            )
            if not (narrative_rejected or timeline_rejected):
                raise ValueError("rejected batch requires narration or timeline rejection evidence")
        elif self.status is VideoBatchStatus.CANCELLED and self.artifact is not None:
            raise ValueError("cancelled batches cannot contain rendered output evidence")

        if (
            self.narration_failure is not None
            and self.status is not VideoBatchStatus.PENDING_BATCH_TTS
        ):
            raise ValueError("batch narration failure is only valid at the manual TTS retry gate")

    def _validate_render_evidence(self, generated: bool) -> None:
        used = [story.used_at for story in self.stories]
        if self.status is VideoBatchStatus.RENDERED:
            if not generated or self.artifact is None or any(value is None for value in used):
                raise ValueError(
                    "rendered batches require merged media and used_at for every story"
                )
            if len(set(used)) != 1:
                raise ValueError("all stories in one render must share the same used_at")
        elif self.artifact is not None or any(value is not None for value in used):
            raise ValueError("only rendered batches may contain artifact or used_at evidence")
        if self.status is VideoBatchStatus.FAILED:
            if self.last_failure is None:
                raise ValueError("failed rendering requires a failure record")
        elif self.last_failure is not None:
            raise ValueError("render failure evidence is only valid while render status is FAILED")


class CreateVideoBatch(DomainModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    template: TemplateDefinition | None = None
    story_ids: list[UUID] = Field(default_factory=list, max_length=15)
    max_stories: int = Field(default=15, ge=1, le=15)
    bgm_track_id: Sha256 | None = None
    bgm_volume: float = Field(default=0.12, ge=0, le=1)
    bgm_loop: bool = True
    template_id: TemplateId = "world_warmth"
    template_version: TemplateVersion = "1.0.0"

    @model_validator(mode="after")
    def validate_story_selection(self) -> CreateVideoBatch:
        if len(self.story_ids) != len(set(self.story_ids)):
            raise ValueError("story_ids must be unique")
        if self.story_ids and len(self.story_ids) > self.max_stories:
            raise ValueError("story_ids cannot exceed max_stories")
        return self


class SubmitNarrationReview(DomainModel):
    expected_batch_version: int = Field(ge=1)
    decision: NarrationReviewDecision
    reviewer_id: NonBlankStr
    note: str | None = None
    revised_script: ScriptDocument | None = None

    @model_validator(mode="after")
    def validate_review(self) -> SubmitNarrationReview:
        if self.decision is NarrationReviewDecision.APPROVE and self.revised_script is not None:
            raise ValueError("narration approval cannot include a revised_script")
        if self.decision is NarrationReviewDecision.REVISE and self.revised_script is None:
            raise ValueError("narration revision requires a revised_script")
        if self.decision is NarrationReviewDecision.REJECT and not self.note:
            raise ValueError("narration rejection requires a note")
        return self


class SynthesizeBatchNarration(DomainModel):
    expected_batch_version: int = Field(ge=1)


class SubmitTimelineReview(DomainModel):
    expected_batch_version: int = Field(ge=1)
    decision: TimelineReviewDecision
    reviewer_id: NonBlankStr
    note: str | None = None
    story_order: list[UUID] | None = Field(default=None, min_length=1, max_length=15)

    @model_validator(mode="after")
    def validate_review(self) -> SubmitTimelineReview:
        if self.story_order is not None and len(self.story_order) != len(set(self.story_order)):
            raise ValueError("story_order must contain unique IDs")
        if self.decision is TimelineReviewDecision.REJECT and not self.note:
            raise ValueError("timeline rejection requires a note")
        return self


class RenderVideoBatch(DomainModel):
    expected_batch_version: int = Field(ge=1)


VIDEO_BATCH_TRANSITIONS: dict[VideoBatchStatus, frozenset[VideoBatchStatus]] = {
    VideoBatchStatus.PENDING_NARRATION_REVIEW: frozenset(
        {
            VideoBatchStatus.PENDING_BATCH_TTS,
            VideoBatchStatus.REJECTED,
            VideoBatchStatus.CANCELLED,
        }
    ),
    VideoBatchStatus.PENDING_BATCH_TTS: frozenset(
        {
            VideoBatchStatus.PENDING_NARRATION_REVIEW,
            VideoBatchStatus.PROCESSING_BATCH_TTS,
            VideoBatchStatus.REJECTED,
            VideoBatchStatus.CANCELLED,
        }
    ),
    VideoBatchStatus.PROCESSING_BATCH_TTS: frozenset(
        {
            VideoBatchStatus.PENDING_BATCH_TTS,
            VideoBatchStatus.PENDING_TIMELINE_REVIEW,
        }
    ),
    VideoBatchStatus.PENDING_TIMELINE_REVIEW: frozenset(
        {
            VideoBatchStatus.PENDING_NARRATION_REVIEW,
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.REJECTED,
            VideoBatchStatus.CANCELLED,
        }
    ),
    VideoBatchStatus.READY_TO_RENDER: frozenset(
        {VideoBatchStatus.RENDERING, VideoBatchStatus.CANCELLED}
    ),
    VideoBatchStatus.RENDERING: frozenset({VideoBatchStatus.RENDERED, VideoBatchStatus.FAILED}),
    VideoBatchStatus.FAILED: frozenset({VideoBatchStatus.RENDERING, VideoBatchStatus.CANCELLED}),
    VideoBatchStatus.RENDERED: frozenset(),
    VideoBatchStatus.REJECTED: frozenset(),
    VideoBatchStatus.CANCELLED: frozenset(),
}


def is_video_batch_transition_allowed(
    current: VideoBatchStatus,
    target: VideoBatchStatus,
) -> bool:
    return target in VIDEO_BATCH_TRANSITIONS[current]


def render_input_sha256(
    props: RemotionVideoProps,
    assets: list[VideoInputAsset],
) -> str:
    """Hash rendered semantics plus content snapshots in a stable order."""

    props_payload = props.model_dump(mode="json")
    if props.outro_duration_ms == 0:
        # This field did not exist in legacy render snapshots. Omitting its
        # compatibility value keeps their immutable review hash verifiable.
        props_payload.pop("outro_duration_ms", None)
    if props.template is None:
        props_payload.pop("template", None)
    if not props.visual_assets:
        props_payload.pop("visual_assets", None)
    episode_plan = props_payload.get("episode_plan")
    if isinstance(episode_plan, dict):
        scenes = episode_plan.get("scenes")
        if isinstance(scenes, list):
            for scene in scenes:
                if not isinstance(scene, dict):
                    continue
                if scene.get("variant_id") is None:
                    scene.pop("variant_id", None)
                if not scene.get("visual_asset_ids"):
                    scene.pop("visual_asset_ids", None)
                if scene.get("primary_visual_asset_id") is None:
                    scene.pop("primary_visual_asset_id", None)
    return _canonical_sha256(
        {
            "props": props_payload,
            "assets": [
                asset.model_dump(mode="json")
                for asset in sorted(assets, key=lambda item: (item.kind.value, item.local_path))
            ],
        }
    )
