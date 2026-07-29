from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator

from god_news.domain.models import DomainModel, utc_now
from god_news.sources.models import NonBlankStr, Sha256Hex, SourceName


class SourceFetchRequest(DomainModel):
    """Provider-neutral page request with an opaque, resumable cursor."""

    limit: int = Field(default=10, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2_000)
    checkpoint: str | None = Field(default=None, max_length=2_000)


class SourceFetchAttempt(DomainModel):
    sequence: int = Field(ge=0)
    operation: Literal["authenticate", "discover", "listing", "item"]
    transport: Literal["official_api", "rss", "atom", "browser", "public_page"]
    outcome: Literal["succeeded", "failed", "stopped"]
    started_at: datetime = Field(default_factory=utc_now)
    duration_ms: float = Field(ge=0)
    endpoint: AnyHttpUrl
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    retryable: bool | None = None
    item_count: int = Field(default=0, ge=0)


class SourceFetchError(DomainModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool = False
    item_external_id: str | None = Field(default=None, max_length=500)


class SourceRightsAssessment(DomainModel):
    """Evidence, not a license grant.

    Connectors may identify an upstream policy, but ambiguous per-file rights
    must remain review-required until a visual-asset adapter verifies them.
    """

    status: Literal[
        "unknown",
        "permission_required",
        "attribution_license",
        "public_domain",
    ]
    policy_url: AnyHttpUrl | None = None
    license_identifier: str | None = Field(default=None, max_length=200)
    license_url: AnyHttpUrl | None = None
    allows_commercial_use: bool | None = None
    allows_derivatives: bool | None = None
    requires_attribution: bool = True
    requires_human_review: bool = True
    personality_rights_warning: bool = False
    trademark_warning: bool = False
    notes: list[NonBlankStr] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def fail_closed_on_uncertain_rights(self) -> SourceRightsAssessment:
        if self.status in {"unknown", "permission_required"} and not self.requires_human_review:
            raise ValueError("uncertain rights must require human review")
        if self.status == "attribution_license" and not self.license_identifier:
            raise ValueError("attribution_license requires a license identifier")
        return self


class SourceMediaCandidate(DomainModel):
    kind: Literal["image", "video", "audio"]
    canonical_source_url: AnyHttpUrl
    direct_download_url: AnyHttpUrl | None = None
    title: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=300)
    credit: str | None = Field(default=None, max_length=500)
    mime_type: str | None = Field(default=None, max_length=200)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    rights: SourceRightsAssessment


class SourceArticle(DomainModel):
    source: SourceName
    external_id: NonBlankStr
    canonical_url: AnyHttpUrl
    title: NonBlankStr
    content_text: NonBlankStr
    published_at: datetime
    language: NonBlankStr
    publisher: NonBlankStr
    author: str | None = None
    categories: list[NonBlankStr] = Field(default_factory=list, max_length=100)
    media_candidates: list[SourceMediaCandidate] = Field(default_factory=list, max_length=100)
    rights: SourceRightsAssessment
    raw_item_sha256: Sha256Hex


class SourceResponseSnapshot(DomainModel):
    endpoint: AnyHttpUrl
    retrieved_at: datetime = Field(default_factory=utc_now)
    content_type: str | None = Field(default=None, max_length=200)
    byte_count: int = Field(ge=0)
    content_sha256: Sha256Hex


class SourceDiscoveryResult(DomainModel):
    source: SourceName
    articles: list[SourceArticle] = Field(default_factory=list, max_length=100)
    attempts: list[SourceFetchAttempt] = Field(default_factory=list, max_length=1_000)
    errors: list[SourceFetchError] = Field(default_factory=list, max_length=100)
    response_snapshot: SourceResponseSnapshot
    next_cursor: str | None = Field(default=None, max_length=2_000)
    checkpoint: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_discovery(self) -> SourceDiscoveryResult:
        if any(article.source != self.source for article in self.articles):
            raise ValueError("all discovered articles must match the connector source")
        sequences = [attempt.sequence for attempt in self.attempts]
        if sequences != list(range(len(sequences))):
            raise ValueError("fetch attempt sequence must be contiguous and zero-based")
        if not self.articles and not self.errors:
            raise ValueError("an empty discovery result requires classified error evidence")
        return self
