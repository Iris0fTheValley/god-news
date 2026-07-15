from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from god_news.domain.models import DomainModel, utc_now
from god_news.sources.models import SourceName
from god_news.sources.run_models import SourceRunStatus

ScheduleId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SourceScheduleState(DomainModel):
    """Durable operator intent and audit evidence for automatic collection."""

    schedule_id: ScheduleId = "source-auto-collection"
    enabled: bool = False
    next_run_at: datetime | None = None
    last_tick_at: datetime | None = None
    last_started_run_ids: dict[SourceName, UUID] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("next_run_at", "last_tick_at", "updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("source schedule timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_enabled_state(self) -> SourceScheduleState:
        if self.enabled and self.next_run_at is None:
            raise ValueError("enabled source schedules require next_run_at")
        if not self.enabled and self.next_run_at is not None:
            raise ValueError("disabled source schedules cannot have next_run_at")
        return self


class ActiveScheduledSourceRun(DomainModel):
    source: SourceName
    run_id: UUID
    status: SourceRunStatus


class SourceScheduleSnapshot(DomainModel):
    """Public control-plane view; cadence remains an operator-only backend policy."""

    schedule_id: ScheduleId
    enabled: bool
    next_run_at: datetime | None
    last_tick_at: datetime | None
    last_started_run_ids: dict[SourceName, UUID]
    ready_sources: list[SourceName]
    active_runs: list[ActiveScheduledSourceRun]
    version: int
    updated_at: datetime
