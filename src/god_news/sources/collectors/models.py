from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from god_news.domain.models import DomainModel, utc_now
from god_news.sources.models import RawSourceItem, SourceName

CollectorState = Literal[
    "disabled",
    "unconfigured",
    "unauthorized",
    "ready",
]
CollectionOutcome = Literal[
    "disabled",
    "unconfigured",
    "unauthorized",
    "succeeded",
    "partial",
    "failed",
    "stopped_captcha",
]
AttemptOutcome = Literal["succeeded", "failed", "stopped"]
CollectionOperation = Literal["authenticate", "discover", "listing", "item"]
DiagnosticOutcome = Literal[
    "disabled",
    "unconfigured",
    "unauthorized",
    "verified",
    "failed",
    "not_supported",
]


class CollectorReadiness(DomainModel):
    source: SourceName
    state: CollectorState
    enabled: bool
    configured: bool
    authorized: bool
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def state_matches_flags(self) -> CollectorReadiness:
        expected: CollectorState
        if not self.enabled:
            expected = "disabled"
        elif not self.configured:
            expected = "unconfigured"
        elif not self.authorized:
            expected = "unauthorized"
        else:
            expected = "ready"
        if self.state != expected:
            raise ValueError("collector readiness state must match readiness flags")
        return self


class CollectionAttempt(DomainModel):
    """Sanitized telemetry for one provider or fallback-layer attempt."""

    sequence: int = Field(ge=0)
    layer: str = Field(min_length=1, max_length=100)
    operation: CollectionOperation
    outcome: AttemptOutcome
    duration_ms: float = Field(ge=0)
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    retryable: bool | None = None
    item_count: int = Field(default=0, ge=0)


class CollectionErrorEvidence(DomainModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool = False


class CollectorDiagnostic(DomainModel):
    """Sanitized result of an explicit operator-requested live diagnostic."""

    source: SourceName
    outcome: DiagnosticOutcome
    checked_at: datetime = Field(default_factory=utc_now)
    credentials_verified: bool | None = None
    endpoint_reachable: bool | None = None
    attempts: list[CollectionAttempt] = Field(default_factory=list, max_length=100)
    errors: list[CollectionErrorEvidence] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_evidence(self) -> CollectorDiagnostic:
        if self.outcome == "verified":
            if self.credentials_verified is not True or self.endpoint_reachable is not True:
                raise ValueError("verified diagnostics require positive live evidence")
            if self.errors:
                raise ValueError("verified diagnostics cannot contain errors")
        elif self.outcome == "failed" and not self.errors:
            raise ValueError("failed diagnostics require error evidence")
        return self


class SourceCollectionRun(DomainModel):
    run_id: UUID = Field(default_factory=uuid4)
    source: SourceName
    outcome: CollectionOutcome
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    duration_ms: float = Field(ge=0)
    # Set by the gateway decorator after it has applied per-source cadence.
    # It is duplicated onto SourceRun so the API/audit record retains it.
    cooldown_wait_ms: float = Field(default=0, ge=0)
    items: list[RawSourceItem] = Field(default_factory=list, max_length=100)
    attempts: list[CollectionAttempt] = Field(default_factory=list, max_length=1_000)
    errors: list[CollectionErrorEvidence] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_run_evidence(self) -> SourceCollectionRun:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("collection timestamps must be timezone-aware")
        self.started_at = self.started_at.astimezone(UTC)
        self.finished_at = self.finished_at.astimezone(UTC)
        if self.finished_at < self.started_at:
            raise ValueError("collection run cannot finish before it starts")
        if any(item.source != self.source for item in self.items):
            raise ValueError("all collected items must match the run source")
        sequences = [attempt.sequence for attempt in self.attempts]
        if sequences != list(range(len(sequences))):
            raise ValueError("collection attempt sequence must be contiguous and zero-based")
        if self.outcome == "succeeded" and (not self.items or self.errors):
            raise ValueError("a successful run requires items and no errors")
        if self.outcome == "partial" and (not self.items or not self.errors):
            raise ValueError("a partial run requires both items and errors")
        if self.outcome in {"disabled", "unconfigured", "unauthorized", "failed"}:
            if self.items:
                raise ValueError(f"{self.outcome} run cannot contain items")
            if not self.errors:
                raise ValueError(f"{self.outcome} run requires an error explanation")
        if self.outcome == "stopped_captcha" and not any(
            error.code == "captcha_detected" for error in self.errors
        ):
            raise ValueError("CAPTCHA stop must retain captcha_detected evidence")
        return self
