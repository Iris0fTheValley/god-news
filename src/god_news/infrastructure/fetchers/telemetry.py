from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from god_news.domain.models import FetchedDocument


class FetchLayerAttempt(BaseModel):
    """One sanitized attempt in the URL fetch fallback chain.

    Provider response bodies and exception strings are intentionally excluded so
    telemetry can be persisted or returned without leaking credentials or page
    content.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: str = Field(min_length=1)
    outcome: Literal["succeeded", "failed"]
    duration_ms: float = Field(ge=0)
    error_code: str | None = None
    retryable: bool | None = None


class TracedFetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: FetchedDocument
    attempts: tuple[FetchLayerAttempt, ...] = Field(min_length=1)

