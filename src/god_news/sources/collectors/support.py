from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter

from god_news.domain.models import utc_now
from god_news.sources.collectors.models import (
    AttemptOutcome,
    CollectionAttempt,
    CollectionErrorEvidence,
    CollectionOperation,
    CollectionOutcome,
    CollectorReadiness,
    SourceCollectionRun,
)
from god_news.sources.models import RawSourceItem, SourceName


class CollectorFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable
        self.http_status = http_status

    def evidence(self) -> CollectionErrorEvidence:
        return CollectionErrorEvidence(
            code=self.code,
            message=self.public_message,
            retryable=self.retryable,
        )


def readiness_for(
    *,
    source: SourceName,
    enabled: bool,
    configured: bool,
    authorized: bool,
    notes: list[str],
) -> CollectorReadiness:
    if not enabled:
        state = "disabled"
    elif not configured:
        state = "unconfigured"
    elif not authorized:
        state = "unauthorized"
    else:
        state = "ready"
    return CollectorReadiness(
        source=source,
        state=state,
        enabled=enabled,
        configured=configured,
        authorized=authorized,
        notes=notes,
    )


def readiness_failure(readiness: CollectorReadiness) -> CollectorFailure | None:
    if readiness.state == "ready":
        return None
    messages = {
        "disabled": "The source collector is disabled by configuration.",
        "unconfigured": "The source collector is missing required configuration.",
        "unauthorized": "The operator has not acknowledged authorized source use.",
    }
    return CollectorFailure(
        f"collector_{readiness.state}",
        messages[readiness.state],
    )


@dataclass(slots=True)
class RunRecorder:
    source: SourceName
    started_at: datetime = field(default_factory=utc_now)
    _started_clock: float = field(default_factory=perf_counter)
    attempts: list[CollectionAttempt] = field(default_factory=list)
    errors: list[CollectionErrorEvidence] = field(default_factory=list)

    def attempt(
        self,
        *,
        layer: str,
        operation: CollectionOperation,
        outcome: AttemptOutcome,
        duration_ms: float,
        http_status: int | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
        item_count: int = 0,
    ) -> None:
        self.attempts.append(
            CollectionAttempt(
                sequence=len(self.attempts),
                layer=layer,
                operation=operation,
                outcome=outcome,
                duration_ms=duration_ms,
                http_status=http_status,
                error_code=error_code,
                retryable=retryable,
                item_count=item_count,
            )
        )

    def fail_readiness(self, failure: CollectorFailure) -> SourceCollectionRun:
        self.errors.append(failure.evidence())
        outcome_by_code: dict[str, CollectionOutcome] = {
            "collector_disabled": "disabled",
            "collector_unconfigured": "unconfigured",
            "collector_unauthorized": "unauthorized",
        }
        return self.finish(items=[], outcome=outcome_by_code[failure.code])

    def finish(
        self,
        *,
        items: list[RawSourceItem],
        outcome: CollectionOutcome | None = None,
    ) -> SourceCollectionRun:
        if outcome is None:
            if items and self.errors:
                outcome = "partial"
            elif items:
                outcome = "succeeded"
            else:
                outcome = "failed"
        finished_at = utc_now()
        return SourceCollectionRun(
            source=self.source,
            outcome=outcome,
            started_at=self.started_at,
            finished_at=finished_at,
            duration_ms=(perf_counter() - self._started_clock) * 1_000,
            items=items,
            attempts=self.attempts,
            errors=self.errors,
        )
