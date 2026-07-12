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

from god_news.domain.enums import ContentCategory
from god_news.domain.models import DomainModel, NonBlankStr, ProductionManifest, utc_now

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class VideoBatchStatus(StrEnum):
    PENDING_TIMELINE_REVIEW = "PENDING_TIMELINE_REVIEW"
    READY_TO_RENDER = "READY_TO_RENDER"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


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


class HostVisualReservations(DomainModel):
    """Current Remotion host contract with typed future asset reservations.

    The renderer remains ``placeholder`` until a concrete Live2D or
    differential-art composition is installed. Assets can already be described
    without leaking provider-specific mappings into the orchestration service.
    """

    renderer: Literal["placeholder"] = "placeholder"
    live2d: Live2DReservation | None = None
    differential_art: DifferentialArtReservation | None = None


class RemotionVideoProps(DomainModel):
    """Backend-owned subset of ``video/src/schema.ts``.

    ``runtime_assets`` is intentionally absent: the local Remotion CLI stages
    files by content hash and owns those transient browser bindings.
    """

    manifest: ProductionManifest
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    intro_duration_ms: int = Field(default=700, ge=0, le=5_000)
    transition_duration_ms: int = Field(default=180, ge=0, le=2_000)
    theme: VideoTheme = Field(default_factory=VideoTheme)
    bgm: BgmRenderSpec | None = None
    visual_reservations: HostVisualReservations = Field(
        default_factory=HostVisualReservations
    )


class VideoBatchStory(DomainModel):
    sequence: int = Field(ge=0, le=14)
    story_id: UUID
    story_version: int = Field(ge=1)
    category: ContentCategory
    title: NonBlankStr
    manifest: ProductionManifest
    chapter_start_ms: int = Field(ge=0)
    chapter_end_ms: int = Field(gt=0)
    reserved_at: datetime = Field(default_factory=utc_now)
    used_at: datetime | None = None

    @field_validator("reserved_at", "used_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_chapter(self) -> VideoBatchStory:
        if self.manifest.story_id != self.story_id:
            raise ValueError("story manifest ID must match story_id")
        if self.chapter_end_ms <= self.chapter_start_ms:
            raise ValueError("chapter_end_ms must be greater than chapter_start_ms")
        if self.chapter_end_ms - self.chapter_start_ms != self.manifest.total_duration_ms:
            raise ValueError("chapter duration must match the story manifest")
        expected_start = 0
        for index, segment in enumerate(self.manifest.timeline):
            if segment.sequence != index:
                raise ValueError("story timeline sequence must be contiguous and zero-based")
            if segment.start_ms != expected_start:
                raise ValueError("story timeline must be contiguous and start at zero")
            expected_start = segment.end_ms
        if expected_start != self.manifest.total_duration_ms:
            raise ValueError("story timeline must end at total_duration_ms")
        return self


class TimelineReview(DomainModel):
    reviewer_id: NonBlankStr
    decision: TimelineReviewDecision
    reviewed_batch_version: int = Field(ge=1)
    story_order: list[UUID] = Field(min_length=1, max_length=15)
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


class VideoRenderArtifact(DomainModel):
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


class VideoBatch(DomainModel):
    batch_id: UUID = Field(default_factory=uuid4)
    status: VideoBatchStatus = VideoBatchStatus.PENDING_TIMELINE_REVIEW
    title: NonBlankStr
    subtitle: str | None = None
    stories: list[VideoBatchStory] = Field(min_length=1, max_length=15)
    bgm: BgmSelection | None = None
    remotion_props: RemotionVideoProps
    input_assets: list[VideoInputAsset] = Field(min_length=1, max_length=1_600)
    render_input_sha256: Sha256
    timeline_review: TimelineReview | None = None
    artifact: VideoRenderArtifact | None = None
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
        if self.remotion_props.manifest.story_id != self.batch_id:
            raise ValueError("aggregate manifest story_id must equal batch_id")
        if (
            self.remotion_props.title != self.title
            or self.remotion_props.subtitle != self.subtitle
        ):
            raise ValueError("Remotion title metadata must match the batch")
        expected_bgm = self.bgm.render_spec() if self.bgm is not None else None
        if self.remotion_props.bgm != expected_bgm:
            raise ValueError("Remotion BGM spec must match the selected catalog track")
        expected_hash = render_input_sha256(self.remotion_props, self.input_assets)
        if self.render_input_sha256 != expected_hash:
            raise ValueError("render_input_sha256 does not match props and input assets")

        asset_keys = [(asset.kind, asset.local_path) for asset in self.input_assets]
        if len(asset_keys) != len(set(asset_keys)):
            raise ValueError("video input assets must not repeat a kind/path pair")
        audio_paths = {segment.audio_path for segment in self.remotion_props.manifest.timeline}
        recorded_audio_paths = {
            asset.local_path
            for asset in self.input_assets
            if asset.kind is VideoInputAssetKind.AUDIO
        }
        if recorded_audio_paths != audio_paths:
            raise ValueError("video input audio evidence must match the aggregate timeline")
        bgm_assets = [
            asset for asset in self.input_assets if asset.kind is VideoInputAssetKind.BGM
        ]
        if self.remotion_props.bgm is None:
            if bgm_assets:
                raise ValueError("batches without BGM cannot retain BGM input evidence")
        elif len(bgm_assets) != 1 or bgm_assets[0].local_path != self.remotion_props.bgm.local_path:
            raise ValueError("BGM input evidence must match the selected BGM path")

        aggregate = self.remotion_props.manifest
        if aggregate.total_duration_ms != self.stories[-1].chapter_end_ms:
            raise ValueError("aggregate duration must end with the final chapter")
        expected_start = 0
        for story in self.stories:
            if story.chapter_start_ms != expected_start:
                raise ValueError("story chapters must be contiguous and start at zero")
            expected_start = story.chapter_end_ms

        aggregate_segments = aggregate.timeline
        source_segments = [
            segment for story in self.stories for segment in story.manifest.timeline
        ]
        if len(aggregate_segments) != len(source_segments):
            raise ValueError("aggregate timeline must contain every story segment")
        cursor = 0
        for index, (combined, source) in enumerate(
            zip(aggregate_segments, source_segments, strict=True)
        ):
            duration = source.end_ms - source.start_ms
            if (
                combined.sequence != index
                or combined.start_ms != cursor
                or combined.end_ms != cursor + duration
                or combined.segment_id != source.segment_id
                or combined.text != source.text
                or combined.speaker_id != source.speaker_id
                or combined.emotion != source.emotion
                or combined.visual_hint != source.visual_hint
                or combined.audio_path != source.audio_path
            ):
                raise ValueError("aggregate timeline does not match ordered story manifests")
            cursor += duration
        if cursor != aggregate.total_duration_ms:
            raise ValueError("aggregate timeline must end at total_duration_ms")

        used = [story.used_at for story in self.stories]
        if self.status is VideoBatchStatus.RENDERED:
            if self.artifact is None or any(value is None for value in used):
                raise ValueError("rendered batches require an artifact and used_at for every story")
            if len(set(used)) != 1:
                raise ValueError("all stories in one render must share the same used_at")
        elif self.artifact is not None or any(value is not None for value in used):
            raise ValueError("only rendered batches may contain artifact or used_at evidence")

        approved_states = {
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.RENDERING,
            VideoBatchStatus.RENDERED,
            VideoBatchStatus.FAILED,
        }
        if (
            self.timeline_review is not None
            and self.timeline_review.story_order != story_ids
        ):
            raise ValueError("timeline review order must match the current batch order")
        if self.status in approved_states:
            if (
                self.timeline_review is None
                or self.timeline_review.decision is not TimelineReviewDecision.APPROVE
            ):
                raise ValueError("renderable batches require an approved timeline review")
        elif self.status is VideoBatchStatus.REJECTED:
            if (
                self.timeline_review is None
                or self.timeline_review.decision is not TimelineReviewDecision.REJECT
            ):
                raise ValueError("rejected batches require rejection review evidence")
        elif self.status is VideoBatchStatus.CANCELLED:
            if self.artifact is not None or any(value is not None for value in used):
                raise ValueError("cancelled batches cannot contain rendered output evidence")
        elif self.timeline_review is not None:
            raise ValueError("pending batches cannot contain timeline review evidence")
        return self


class CreateVideoBatch(DomainModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    story_ids: list[UUID] = Field(default_factory=list, max_length=15)
    max_stories: int = Field(default=15, ge=1, le=15)
    bgm_track_id: Sha256 | None = None
    bgm_volume: float = Field(default=0.12, ge=0, le=1)
    bgm_loop: bool = True

    @model_validator(mode="after")
    def validate_story_selection(self) -> CreateVideoBatch:
        if len(self.story_ids) != len(set(self.story_ids)):
            raise ValueError("story_ids must be unique")
        if self.story_ids and len(self.story_ids) > self.max_stories:
            raise ValueError("story_ids cannot exceed max_stories")
        return self


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
    VideoBatchStatus.PENDING_TIMELINE_REVIEW: frozenset(
        {
            VideoBatchStatus.READY_TO_RENDER,
            VideoBatchStatus.REJECTED,
            VideoBatchStatus.CANCELLED,
        }
    ),
    VideoBatchStatus.READY_TO_RENDER: frozenset(
        {VideoBatchStatus.RENDERING, VideoBatchStatus.CANCELLED}
    ),
    VideoBatchStatus.RENDERING: frozenset(
        {VideoBatchStatus.RENDERED, VideoBatchStatus.FAILED, VideoBatchStatus.CANCELLED}
    ),
    VideoBatchStatus.FAILED: frozenset(
        {VideoBatchStatus.RENDERING, VideoBatchStatus.CANCELLED}
    ),
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

    payload = {
        "props": props.model_dump(mode="json"),
        "assets": [
            asset.model_dump(mode="json")
            for asset in sorted(assets, key=lambda item: (item.kind.value, item.local_path))
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
