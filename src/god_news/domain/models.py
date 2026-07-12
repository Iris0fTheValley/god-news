from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from god_news.domain.enums import (
    AudioFormat,
    ContentCategory,
    ReviewDecision,
    ReviewStage,
    SourceKind,
    StoryStatus,
)
from god_news.sources.models import NormalizedSourceItem, RawSourceItem

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UrlSource(DomainModel):
    kind: Literal[SourceKind.URL] = SourceKind.URL
    url: AnyHttpUrl


class TextSource(DomainModel):
    kind: Literal[SourceKind.TEXT] = SourceKind.TEXT
    text: Annotated[str, StringConstraints(min_length=1, max_length=500_000)]
    title: NonBlankStr = "Uploaded text"
    language: NonBlankStr | None = None


SourceRequest = Annotated[UrlSource | TextSource, Field(discriminator="kind")]


class IngestRequest(DomainModel):
    source: SourceRequest
    target_language: NonBlankStr = "zh-CN"
    style: NonBlankStr = "clear, accurate short-video narration"
    target_duration_seconds: int = Field(default=90, ge=15, le=600)
    speaker_id: NonBlankStr = "narrator"
    emotion: NonBlankStr = "neutral"
    speed: float = Field(default=1.0, ge=0.6, le=1.65)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)


class SourceItemIngestRequest(DomainModel):
    """Trusted adapter boundary for one of the four fixed sources.

    Network-facing adapters must map their documented/authorized response into
    ``RawSourceItem`` before calling this boundary. The core never consumes an
    upstream provider's unvalidated mapping.
    """

    item: RawSourceItem
    target_language: NonBlankStr = "zh-CN"
    style: NonBlankStr = "clear, accurate short-video narration"
    target_duration_seconds: int = Field(default=90, ge=15, le=600)
    speaker_id: NonBlankStr = "narrator"
    emotion: NonBlankStr = "neutral"
    speed: float = Field(default=1.0, ge=0.6, le=1.65)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)


class SourceSnapshot(DomainModel):
    kind: SourceKind
    source_uri: str
    final_uri: str
    title: NonBlankStr
    author: str | None = None
    published_at: datetime | None = None
    detected_language: str | None = None
    fetcher: NonBlankStr
    fetched_at: datetime = Field(default_factory=utc_now)
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class FetchedDocument(DomainModel):
    source: SourceSnapshot
    content: NonBlankStr

    @classmethod
    def from_text(cls, request: TextSource) -> FetchedDocument:
        digest = sha256(request.text.encode("utf-8")).hexdigest()
        return cls(
            source=SourceSnapshot(
                kind=SourceKind.TEXT,
                source_uri="text://user-upload",
                final_uri="text://user-upload",
                title=request.title,
                detected_language=request.language,
                fetcher="text",
                content_sha256=digest,
            ),
            content=request.text,
        )

    @classmethod
    def from_normalized_source(cls, item: NormalizedSourceItem) -> FetchedDocument:
        canonical_url = str(item.canonical_url)
        return cls(
            source=SourceSnapshot(
                kind=SourceKind.FIXED_SOURCE,
                source_uri=canonical_url,
                final_uri=canonical_url,
                title=item.title,
                author=item.author,
                published_at=item.published_at,
                detected_language=item.language,
                fetcher=f"source-contract:{item.source}",
                content_sha256=item.content_sha256,
            ),
            content=item.content_text,
        )


class EditorialScreening(DomainModel):
    """AI screening evidence plus the current human-reviewable decision.

    Model fields are immutable evidence. Review edits update only ``category``
    and ``candidate_recommendation``, so acceptance metrics remain auditable.
    """

    model_category: ContentCategory
    category: ContentCategory
    model_candidate_recommendation: bool
    candidate_recommendation: bool
    confidence: float = Field(ge=0, le=1)
    rationale: NonBlankStr
    risk_flags: list[NonBlankStr] = Field(default_factory=list, max_length=20)
    secondary_categories: list[ContentCategory] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_categories(self) -> EditorialScreening:
        if self.model_category in self.secondary_categories:
            raise ValueError("primary model category cannot also be secondary")
        if len(self.secondary_categories) != len(set(self.secondary_categories)):
            raise ValueError("secondary categories must be unique")
        return self


class TranslationResult(DomainModel):
    source_language: NonBlankStr
    target_language: NonBlankStr
    translated_text: NonBlankStr
    summary: NonBlankStr
    key_points: list[NonBlankStr] = Field(default_factory=list, max_length=20)
    screening: EditorialScreening


class ScriptPreferences(DomainModel):
    style: NonBlankStr
    target_duration_seconds: int = Field(ge=15, le=600)
    speaker_id: NonBlankStr
    emotion: NonBlankStr = "neutral"
    speed: float = Field(default=1.0, ge=0.6, le=1.65)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)


class ScriptSegmentDraft(DomainModel):
    text: NonBlankStr
    speaker_id: NonBlankStr = "narrator"
    emotion: NonBlankStr = "neutral"
    speed: float = Field(default=1.0, ge=0.6, le=1.65)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    visual_hint: str | None = None


class ScriptDraft(DomainModel):
    title: NonBlankStr
    language: NonBlankStr
    segments: list[ScriptSegmentDraft] = Field(min_length=1, max_length=100)


class ScriptSegment(DomainModel):
    segment_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=0)
    text: NonBlankStr
    speaker_id: NonBlankStr
    emotion: NonBlankStr
    speed: float = Field(ge=0.6, le=1.65)
    pitch: float = Field(ge=-12.0, le=12.0)
    visual_hint: str | None = None


class ScriptDocument(DomainModel):
    revision: int = Field(default=1, ge=1)
    title: NonBlankStr
    language: NonBlankStr
    segments: list[ScriptSegment] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_sequences(self) -> ScriptDocument:
        expected = list(range(len(self.segments)))
        actual = [segment.sequence for segment in self.segments]
        if actual != expected:
            raise ValueError("script segment sequence must be contiguous and zero-based")
        ids = [segment.segment_id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("script segment_id values must be unique")
        return self

    @classmethod
    def from_draft(cls, draft: ScriptDraft, *, revision: int = 1) -> ScriptDocument:
        return cls(
            revision=revision,
            title=draft.title,
            language=draft.language,
            segments=[
                ScriptSegment(sequence=index, **segment.model_dump())
                for index, segment in enumerate(draft.segments)
            ],
        )


class AudioClip(DomainModel):
    segment_id: UUID
    path: NonBlankStr
    format: AudioFormat = AudioFormat.WAV
    duration_ms: int = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class SynthesisMetadata(DomainModel):
    seed: int
    reference_audio_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    runtime_config_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    gpt_weights_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    sovits_weights_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    prompt_language: NonBlankStr
    text_language: NonBlankStr


class AudioBundle(DomainModel):
    revision: int = Field(ge=1)
    provider: NonBlankStr
    model_identity: NonBlankStr
    synthesis: SynthesisMetadata
    generated_at: datetime = Field(default_factory=utc_now)
    clips: list[AudioClip] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_segments(self) -> AudioBundle:
        ids = [clip.segment_id for clip in self.clips]
        if len(ids) != len(set(ids)):
            raise ValueError("audio clips must have unique segment_id values")
        return self


class TimelineSegment(DomainModel):
    segment_id: UUID
    sequence: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: NonBlankStr
    speaker_id: NonBlankStr
    emotion: NonBlankStr
    visual_hint: str | None = None
    audio_path: NonBlankStr

    @model_validator(mode="after")
    def validate_time_range(self) -> TimelineSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ProductionManifest(DomainModel):
    schema_version: Literal["1.0"] = "1.0"
    story_id: UUID
    script_revision: int = Field(ge=1)
    language: NonBlankStr
    total_duration_ms: int = Field(gt=0)
    timeline: list[TimelineSegment] = Field(min_length=1)


class PipelineFailure(DomainModel):
    code: NonBlankStr
    message: NonBlankStr
    retryable: bool
    occurred_at: datetime = Field(default_factory=utc_now)


class Story(DomainModel):
    story_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    status: StoryStatus
    # This is the editable editorial headline.  ``source.title`` remains the
    # immutable title captured with the source evidence/provenance.
    title: NonBlankStr | None = None
    source: SourceSnapshot
    provenance: NormalizedSourceItem | None = None
    original_text: NonBlankStr
    target_language: NonBlankStr
    preferences: ScriptPreferences
    translation: TranslationResult | None = None
    script: ScriptDocument | None = None
    audio: AudioBundle | None = None
    last_failure: PipelineFailure | None = None
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
    def validate_provenance_evidence(self) -> Story:
        if self.provenance is None:
            if self.source.kind is SourceKind.FIXED_SOURCE:
                raise ValueError("fixed-source stories require normalized provenance")
            return self
        if self.source.kind is not SourceKind.FIXED_SOURCE:
            raise ValueError("normalized provenance requires fixed_source kind")
        canonical_url = str(self.provenance.canonical_url)
        if self.source.final_uri != canonical_url or self.source.source_uri != canonical_url:
            raise ValueError("source snapshot URI must match normalized canonical URL")
        if self.source.content_sha256 != self.provenance.content_sha256:
            raise ValueError("source snapshot hash must match normalized provenance")
        if self.original_text != self.provenance.content_text:
            raise ValueError("original text must match normalized source content")
        return self

    @property
    def canonical_source_uri(self) -> str | None:
        if self.provenance is not None:
            return str(self.provenance.canonical_url)
        if self.source.kind is SourceKind.URL:
            return self.source.final_uri
        return None


class StoryUpdate(DomainModel):
    """Concurrent-safe edits to mutable editorial settings only.

    The source snapshot, normalized provenance, original text, target language,
    and voice controls intentionally are not part of this public write model.
    """

    expected_story_version: int = Field(ge=1)
    title: NonBlankStr | None = None
    style: NonBlankStr | None = None
    target_duration_seconds: int | None = Field(default=None, ge=15, le=600)

    @model_validator(mode="after")
    def require_edit(self) -> StoryUpdate:
        if (
            self.title is None
            and self.style is None
            and self.target_duration_seconds is None
        ):
            raise ValueError("at least one mutable story field must be supplied")
        return self


class ReviewRecord(DomainModel):
    review_id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    stage: ReviewStage
    decision: ReviewDecision
    reviewer_id: NonBlankStr
    note: str | None = None
    reviewed_story_version: int = Field(ge=1)
    translation_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    script_revision: int | None = Field(default=None, ge=1)
    audio_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = None
    request_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    ai_category: ContentCategory | None = None
    human_category: ContentCategory | None = None
    classification_accepted: bool | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_classification_audit(self) -> ReviewRecord:
        values = (self.ai_category, self.human_category, self.classification_accepted)
        if self.stage is ReviewStage.FIRST:
            if any(value is None for value in values):
                raise ValueError("first review requires classification audit fields")
        elif any(value is not None for value in values):
            raise ValueError("classification audit fields only belong to first review")
        return self


class FirstReviewSubmission(DomainModel):
    review_id: UUID = Field(default_factory=uuid4)
    expected_story_version: int = Field(ge=1)
    decision: ReviewDecision
    reviewer_id: NonBlankStr
    note: str | None = None
    corrected_translation: str | None = None
    corrected_summary: str | None = None
    corrected_key_points: list[NonBlankStr] | None = Field(default=None, max_length=20)
    corrected_category: ContentCategory | None = None
    corrected_candidate_recommendation: bool | None = None
    preferences: ScriptPreferences | None = None

    @model_validator(mode="after")
    def require_change_details(self) -> FirstReviewSubmission:
        has_change = (
            any(
                (
                    self.note,
                    self.corrected_translation,
                    self.corrected_summary,
                    self.corrected_key_points,
                    self.corrected_category,
                    self.preferences,
                )
            )
            or self.corrected_candidate_recommendation is not None
        )
        if self.decision is ReviewDecision.REQUEST_CHANGES and not has_change:
            raise ValueError("request_changes requires a note or correction")
        return self


class SecondReviewSubmission(DomainModel):
    review_id: UUID = Field(default_factory=uuid4)
    expected_story_version: int = Field(ge=1)
    decision: ReviewDecision
    reviewer_id: NonBlankStr
    note: str | None = None
    revised_script: ScriptDocument | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> SecondReviewSubmission:
        if self.decision is ReviewDecision.APPROVE and self.revised_script is not None:
            raise ValueError("approve cannot include a revised_script")
        if self.decision is ReviewDecision.REQUEST_CHANGES and not (
            self.note or self.revised_script
        ):
            raise ValueError("request_changes requires a note or revised_script")
        return self


class StateTransition(DomainModel):
    transition_id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    from_status: StoryStatus
    to_status: StoryStatus
    reason: NonBlankStr
    occurred_at: datetime = Field(default_factory=utc_now)


class MemoryQuery(DomainModel):
    query: NonBlankStr
    agent_id: NonBlankStr = "god-news-editor"
    limit: int = Field(default=5, ge=0, le=20)
    approved_only: bool = True


class MemoryItem(DomainModel):
    memory_id: NonBlankStr
    content: NonBlankStr
    score: float = Field(ge=0, le=1)
    category: str | None = None
    approved: bool


class MemoryWrite(DomainModel):
    content: NonBlankStr
    agent_id: NonBlankStr = "god-news-editor"
    category: NonBlankStr
    story_id: UUID
    approved: bool
    source_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class HealthReport(DomainModel):
    ready: bool
    checks: list[NonBlankStr]


class ClassificationMetrics(DomainModel):
    reviewed_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    accuracy: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> ClassificationMetrics:
        if self.accepted_count > self.reviewed_count:
            raise ValueError("accepted_count cannot exceed reviewed_count")
        if (self.reviewed_count == 0) != (self.accuracy is None):
            raise ValueError("accuracy must be null exactly when no classifications were reviewed")
        return self
