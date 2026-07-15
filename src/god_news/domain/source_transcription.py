from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, field_validator, model_validator

from god_news.domain.models import CaptionVariant, DomainModel, NonBlankStr, utc_now
from god_news.domain.source_media import Sha256Hex, SourceMediaArtifact

LanguageCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=35),
]


class SourceTranscriptionStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TranscriptReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ASRSegment(DomainModel):
    sequence: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: NonBlankStr
    average_log_probability: float | None = None
    no_speech_probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_interval(self) -> ASRSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("ASR segment end_ms must be greater than start_ms")
        return self


class ASRTranscript(DomainModel):
    detected_language: LanguageCode
    language_probability: float = Field(ge=0, le=1)
    segments: list[ASRSegment] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_segments(self) -> ASRTranscript:
        previous_end = 0
        for index, segment in enumerate(self.segments):
            if segment.sequence != index:
                raise ValueError("ASR segment sequence must be contiguous and zero-based")
            if segment.start_ms < previous_end:
                raise ValueError("ASR segments must not overlap")
            previous_end = segment.end_ms
        return self


class TimedCaptionCue(DomainModel):
    cue_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    captions: list[CaptionVariant] = Field(min_length=1, max_length=20)
    average_log_probability: float | None = None
    no_speech_probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_cue(self) -> TimedCaptionCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("caption cue end_ms must be greater than start_ms")
        keys = [(item.language.casefold(), item.kind) for item in self.captions]
        if len(keys) != len(set(keys)):
            raise ValueError("caption language/kind pairs must be unique within a cue")
        if len([item for item in self.captions if item.kind == "verbatim"]) != 1:
            raise ValueError("caption cues require exactly one verbatim caption")
        return self


class SourceTranscriptionFailure(DomainModel):
    code: NonBlankStr
    message: NonBlankStr
    retryable: bool
    occurred_at: datetime = Field(default_factory=utc_now)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class TranscriptReview(DomainModel):
    reviewer_id: NonBlankStr
    decision: TranscriptReviewDecision
    reviewed_version: int = Field(ge=1)
    note: str | None = None
    reviewed_at: datetime = Field(default_factory=utc_now)

    @field_validator("reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class SourceMediaTranscription(DomainModel):
    transcription_id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    artifact_id: UUID
    artifact_sha256: Sha256Hex
    model_identity: NonBlankStr
    source_language_hint: LanguageCode | None = None
    target_caption_language: LanguageCode
    status: SourceTranscriptionStatus = SourceTranscriptionStatus.QUEUED
    requested_by: NonBlankStr
    attempt_count: int = Field(default=0, ge=0)
    detected_language: LanguageCode | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    cues: list[TimedCaptionCue] = Field(default_factory=list, max_length=10_000)
    reviews: list[TranscriptReview] = Field(default_factory=list, max_length=100)
    failures: list[SourceTranscriptionFailure] = Field(default_factory=list, max_length=100)
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
    def validate_state(self) -> SourceMediaTranscription:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        has_result = self.detected_language is not None and bool(self.cues)
        if self.status in {
            SourceTranscriptionStatus.PENDING_REVIEW,
            SourceTranscriptionStatus.APPROVED,
            SourceTranscriptionStatus.REJECTED,
        } and not has_result:
            raise ValueError("reviewable transcription states require timed captions")
        if self.status in {
            SourceTranscriptionStatus.QUEUED,
            SourceTranscriptionStatus.PROCESSING,
        } and has_result:
            raise ValueError("active transcription states cannot expose stale results")
        if self.status in {
            SourceTranscriptionStatus.FAILED,
            SourceTranscriptionStatus.CANCELLED,
        } and not self.failures:
            raise ValueError("failed or cancelled transcriptions require failure evidence")
        if self.status is SourceTranscriptionStatus.APPROVED:
            if (
                not self.reviews
                or self.reviews[-1].decision is not TranscriptReviewDecision.APPROVE
            ):
                raise ValueError("approved transcriptions require an approval review")
        if self.status is SourceTranscriptionStatus.REJECTED:
            if not self.reviews or self.reviews[-1].decision is not TranscriptReviewDecision.REJECT:
                raise ValueError("rejected transcriptions require a rejection review")
        self._validate_cues()
        return self

    def _validate_cues(self) -> None:
        previous_end = 0
        for index, cue in enumerate(self.cues):
            if cue.sequence != index:
                raise ValueError("caption cue sequence must be contiguous and zero-based")
            if cue.start_ms < previous_end:
                raise ValueError("caption cues must not overlap")
            previous_end = cue.end_ms
            verbatim = next(item for item in cue.captions if item.kind == "verbatim")
            if (
                self.detected_language is not None
                and verbatim.language.casefold() != self.detected_language.casefold()
            ):
                raise ValueError("verbatim cue language must match detected_language")
            translation = [item for item in cue.captions if item.kind == "translation"]
            same_language = (
                self.detected_language is not None
                and self.detected_language.casefold()
                == self.target_caption_language.casefold()
            )
            if same_language and translation:
                raise ValueError("same-language transcripts cannot contain translation cues")
            if not same_language and self.detected_language is not None:
                if len(translation) != 1:
                    raise ValueError("cross-language transcripts require one translation per cue")
                if translation[0].language.casefold() != self.target_caption_language.casefold():
                    raise ValueError("translation cue language must match target_caption_language")

    def evolve(self, **updates: object) -> SourceMediaTranscription:
        """Apply one transition while re-running every domain invariant."""

        payload = self.model_dump()
        payload.update(updates)
        return SourceMediaTranscription.model_validate(payload)


class StartSourceTranscriptionRequest(DomainModel):
    expected_story_version: int = Field(ge=1)
    requested_by: NonBlankStr
    source_language_hint: LanguageCode | None = None
    target_caption_language: LanguageCode = "zh-CN"


class ReviewSourceTranscriptionRequest(DomainModel):
    expected_version: int = Field(ge=1)
    reviewer_id: NonBlankStr
    decision: TranscriptReviewDecision
    revised_cues: list[TimedCaptionCue] | None = Field(default=None, min_length=1)
    note: str | None = None


class CaptionTranslationInput(DomainModel):
    cue_id: UUID
    text: NonBlankStr


class SourceMediaTranscriberError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SourceMediaTranscriber(Protocol):
    @property
    def model_identity(self) -> str: ...

    async def transcribe(self, path: Path, *, language_hint: str | None) -> ASRTranscript: ...


class VerifiedSourceMediaReader(Protocol):
    async def media_path(
        self,
        story_id: UUID,
        artifact_id: UUID,
    ) -> tuple[SourceMediaArtifact, Path]: ...


class TimedCaptionTranslator(Protocol):
    @property
    def name(self) -> str: ...

    async def translate(
        self,
        *,
        transcription_id: UUID,
        source_language: str,
        target_language: str,
        cues: Sequence[CaptionTranslationInput],
    ) -> dict[UUID, str]: ...


class SourceTranscriptionRepository(Protocol):
    async def find_equivalent(
        self,
        *,
        artifact_id: UUID,
        artifact_sha256: str,
        model_identity: str,
        source_language_hint: str | None,
        target_caption_language: str,
    ) -> SourceMediaTranscription | None: ...

    async def create_or_get(
        self,
        transcription: SourceMediaTranscription,
    ) -> SourceMediaTranscription: ...

    async def get(self, transcription_id: UUID) -> SourceMediaTranscription: ...

    async def list_for_artifact(self, artifact_id: UUID) -> Sequence[SourceMediaTranscription]: ...

    async def save(
        self,
        transcription: SourceMediaTranscription,
        *,
        expected_version: int,
    ) -> SourceMediaTranscription: ...

    async def recover_interrupted(self) -> int: ...
