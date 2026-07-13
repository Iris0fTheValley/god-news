from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, computed_field, field_validator, model_validator

from god_news.domain.enums import SpeechEmotion
from god_news.domain.models import DomainModel, normalize_legacy_speech_emotion, utc_now
from god_news.sources.collectors.models import (
    CollectionAttempt,
    CollectionErrorEvidence,
    CollectionOutcome,
    CollectorReadiness,
)
from god_news.sources.models import SourceName

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceRunStatus(StrEnum):
    QUEUED = "queued"
    COLLECTING = "collecting"
    INGESTING = "ingesting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceItemIngestionOutcome(StrEnum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class SourceRunRequest(DomainModel):
    source: SourceName
    limit: int = Field(default=10, ge=1, le=50)
    target_language: NonBlankStr = "zh-CN"
    style: NonBlankStr = "clear, accurate short-video narration"
    target_duration_seconds: int = Field(default=90, ge=15, le=600)
    speaker_id: NonBlankStr = "narrator"
    emotion: SpeechEmotion = SpeechEmotion.HAPPINESS
    speed: float = Field(default=1.0, ge=0.6, le=1.65)
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    requested_by: NonBlankStr

    @field_validator("emotion", mode="before")
    @classmethod
    def normalize_legacy_emotion(cls, value: object) -> object:
        return normalize_legacy_speech_emotion(value)


class SourceItemIngestionResult(DomainModel):
    external_id: NonBlankStr
    outcome: SourceItemIngestionOutcome
    story_id: UUID | None = None
    error_code: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> SourceItemIngestionResult:
        if self.outcome is SourceItemIngestionOutcome.INGESTED:
            if self.story_id is None or self.error_code is not None:
                raise ValueError("ingested items require only a story_id")
        elif self.outcome is SourceItemIngestionOutcome.DUPLICATE:
            if self.story_id is None or self.error_code != "duplicate_story":
                raise ValueError("duplicate items require existing story evidence")
        elif self.error_code is None:
            raise ValueError("failed items require an error_code")
        return self


class SourceRun(DomainModel):
    run_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    request: SourceRunRequest
    status: SourceRunStatus = SourceRunStatus.QUEUED
    collector_outcome: CollectionOutcome | None = None
    attempts: list[CollectionAttempt] = Field(default_factory=list, max_length=1_000)
    collection_errors: list[CollectionErrorEvidence] = Field(default_factory=list, max_length=100)
    cooldown_wait_ms: float = Field(default=0, ge=0)
    items_discovered: int = Field(default=0, ge=0, le=100)
    item_results: list[SourceItemIngestionResult] = Field(default_factory=list, max_length=100)
    run_error: CollectionErrorEvidence | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "started_at", "finished_at", "updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("source run timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ingested_count(self) -> int:
        return sum(
            result.outcome is SourceItemIngestionOutcome.INGESTED
            for result in self.item_results
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duplicate_count(self) -> int:
        return sum(
            result.outcome is SourceItemIngestionOutcome.DUPLICATE
            for result in self.item_results
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_count(self) -> int:
        return sum(
            result.outcome is SourceItemIngestionOutcome.FAILED
            for result in self.item_results
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failure_rate(self) -> float | None:
        if not self.item_results:
            return None
        return self.failed_count / len(self.item_results)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> SourceRun:
        terminal = {
            SourceRunStatus.COMPLETED,
            SourceRunStatus.FAILED,
            SourceRunStatus.CANCELLED,
        }
        if self.status is SourceRunStatus.QUEUED:
            if self.started_at is not None:
                raise ValueError("queued source runs cannot have started")
        elif self.started_at is None:
            raise ValueError("active and terminal source runs require started_at")
        if self.status in terminal:
            if self.finished_at is None:
                raise ValueError("terminal source runs require finished_at")
        elif self.finished_at is not None:
            raise ValueError("non-terminal source runs cannot have finished_at")
        if self.status in {SourceRunStatus.FAILED, SourceRunStatus.CANCELLED}:
            if self.run_error is None:
                raise ValueError("failed and cancelled source runs require run_error")
        elif self.run_error is not None:
            raise ValueError("only failed or cancelled source runs may have run_error")
        if len(self.item_results) > self.items_discovered:
            raise ValueError("item results cannot exceed discovered items")
        if self.status is SourceRunStatus.COMPLETED:
            if self.collector_outcome is None:
                raise ValueError("completed source runs require a collector outcome")
            if len(self.item_results) != self.items_discovered:
                raise ValueError("completed source runs require a result for every item")
        return self


class SourceRunReadiness(DomainModel):
    collectors: list[CollectorReadiness] = Field(min_length=4, max_length=4)
