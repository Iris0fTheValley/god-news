"""Typed, fail-closed contracts for Wikimedia Commons visual discovery.

These models intentionally describe discovery evidence, not locally stored
assets.  A caller can ask only for a search term or a Commons file identity;
download URLs, media facts and licence decisions are derived from the official
Commons API response by an infrastructure adapter.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, Field, StringConstraints, model_validator

from god_news.domain.models import DomainModel, NonBlankStr

CommonsSha1 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]


class CommonsMediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class CommonsLicense(StrEnum):
    """The deliberately small publication allowlist understood by this product."""

    PUBLIC_DOMAIN = "public_domain"
    CC0 = "cc0"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    UNKNOWN = "unknown"


class CommonsDiscoveryRequest(DomainModel):
    """A client may name a Commons file, page id, or search query -- nothing else."""

    query: Annotated[str | None, StringConstraints(min_length=1, max_length=300)] = None
    file_title: Annotated[str | None, StringConstraints(min_length=6, max_length=500)] = None
    page_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def require_exactly_one_selector(self) -> CommonsDiscoveryRequest:
        selectors = [self.query, self.file_title, self.page_id]
        if sum(value is not None for value in selectors) != 1:
            raise ValueError("provide exactly one of query, file_title, or page_id")
        if self.file_title is not None and not self.file_title.casefold().startswith("file:"):
            raise ValueError("file_title must begin with 'File:'")
        return self


class CommonsRights(DomainModel):
    """A licence assessment derived only from metadata supplied by Commons."""

    license: CommonsLicense
    source_license_label: str | None = Field(default=None, max_length=300)
    license_url: AnyHttpUrl | None = None
    allows_commercial_use: bool
    allows_derivatives: bool
    requires_attribution: bool
    requires_human_review: bool

    @model_validator(mode="after")
    def enforce_fail_closed_policy(self) -> CommonsRights:
        reusable = {
            CommonsLicense.PUBLIC_DOMAIN: (False, False),
            CommonsLicense.CC0: (False, False),
            CommonsLicense.CC_BY: (True, True),
            CommonsLicense.CC_BY_SA: (True, True),
        }
        if self.license is CommonsLicense.UNKNOWN:
            if (
                self.allows_commercial_use
                or self.allows_derivatives
                or not self.requires_human_review
            ):
                raise ValueError("unknown Commons rights must fail closed and require human review")
            return self
        expected_attribution, _ = reusable[self.license]
        if not self.allows_commercial_use or not self.allows_derivatives:
            raise ValueError("allowlisted Commons licences must permit commercial derivatives")
        if self.requires_attribution != expected_attribution:
            raise ValueError("Commons licence attribution requirement is inconsistent")
        return self


class CommonsAttribution(DomainModel):
    """Human-readable facts needed to make a later attribution card."""

    author: str | None = Field(default=None, max_length=1_000)
    credit: str | None = Field(default=None, max_length=2_000)
    attribution_text: NonBlankStr


class CommonsVideoDerivative(DomainModel):
    """One official transcoding offered by TimedMediaHandler."""

    url: AnyHttpUrl
    mime_type: Annotated[str, StringConstraints(pattern=r"^video/")]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bandwidth: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_commons_upload_url(self) -> CommonsVideoDerivative:
        if _host(self.url) != "upload.wikimedia.org":
            raise ValueError("Commons derivatives must use upload.wikimedia.org over HTTPS")
        return self


class CommonsVisualCandidate(DomainModel):
    """One typed and rights-assessed result from the official Commons API."""

    file_title: NonBlankStr
    page_id: int = Field(ge=1)
    canonical_page_url: AnyHttpUrl
    direct_download_url: AnyHttpUrl
    kind: CommonsMediaKind
    mime_type: NonBlankStr
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    size_bytes: int = Field(gt=0)
    sha1: CommonsSha1
    attribution: CommonsAttribution
    rights: CommonsRights
    video_derivatives: list[CommonsVideoDerivative] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_candidate_type_and_origins(self) -> CommonsVisualCandidate:
        if not self.file_title.casefold().startswith("file:"):
            raise ValueError("Commons candidates must identify a File: page")
        if _host(self.canonical_page_url) != "commons.wikimedia.org":
            raise ValueError("Commons page URLs must use commons.wikimedia.org over HTTPS")
        if _host(self.direct_download_url) != "upload.wikimedia.org":
            raise ValueError("Commons downloads must use upload.wikimedia.org over HTTPS")
        mime = self.mime_type.casefold()
        if self.kind is CommonsMediaKind.IMAGE:
            if not mime.startswith("image/"):
                raise ValueError("image candidate must have an image MIME type")
            if self.duration_ms is not None or self.video_derivatives:
                raise ValueError("image candidate cannot include video timing or derivatives")
        elif not mime.startswith("video/"):
            raise ValueError("video candidate must have a video MIME type")
        elif self.duration_ms is None:
            raise ValueError("video candidate requires a duration")
        return self

    @property
    def publish_eligible(self) -> bool:
        return (
            self.rights.allows_commercial_use
            and self.rights.allows_derivatives
            and not self.rights.requires_human_review
        )


class CommonsDiscoveryResult(DomainModel):
    request: CommonsDiscoveryRequest
    candidates: list[CommonsVisualCandidate] = Field(default_factory=list, max_length=20)


class VisualDiscoveryStatus(StrEnum):
    """Editorial state of a persisted provider-derived asset candidate."""

    STAGED = "staged"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class StageCommonsVisualRequest(DomainModel):
    """Only stable Commons identity and the target script segment cross the API."""

    file_title: Annotated[str | None, StringConstraints(min_length=6, max_length=500)] = None
    page_id: int | None = Field(default=None, ge=1)
    story_id: UUID
    segment_id: UUID
    expected_story_version: int = Field(ge=0)
    expected_script_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def require_exactly_one_commons_identity(self) -> StageCommonsVisualRequest:
        if (self.file_title is None) == (self.page_id is None):
            raise ValueError("provide exactly one of file_title or page_id")
        if self.file_title is not None and not self.file_title.casefold().startswith("file:"):
            raise ValueError("file_title must begin with 'File:'")
        return self


class ReuseApprovedVisualRequest(DomainModel):
    """Bind already verified Commons bytes to another current narration segment."""

    story_id: UUID
    segment_id: UUID
    expected_story_version: int = Field(ge=0)
    expected_script_revision: int = Field(ge=1)


class VisualDiscoveryReviewRequest(DomainModel):
    expected_story_version: int = Field(ge=0)
    note: Annotated[str | None, StringConstraints(max_length=2_000)] = None


class PersistedVisualDiscoveryAsset(DomainModel):
    asset_id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    segment_id: UUID
    script_revision: int = Field(ge=1)
    status: VisualDiscoveryStatus
    candidate: CommonsVisualCandidate
    storage_key: str | None = Field(default=None, max_length=500)
    sha256: Annotated[str | None, StringConstraints(pattern=r"^[a-f0-9]{64}$")] = None
    downloaded_size_bytes: int | None = Field(default=None, gt=0)
    probed_duration_ms: int | None = Field(default=None, gt=0)
    review_note: str | None = Field(default=None, max_length=2_000)
    reviewed_at: datetime | None = None
    created_at: datetime

    @model_validator(mode="after")
    def bind_download_state_to_status(self) -> PersistedVisualDiscoveryAsset:
        downloaded = (self.storage_key, self.sha256, self.downloaded_size_bytes)
        if any(value is None for value in downloaded) and any(
            value is not None for value in downloaded
        ):
            raise ValueError("download evidence must be complete or absent")
        if self.status in {
            VisualDiscoveryStatus.APPROVED,
            VisualDiscoveryStatus.SUPERSEDED,
        } and any(value is None for value in downloaded):
            raise ValueError("approved or superseded assets require downloaded evidence")
        return self


class VisualDiscoveryAssetView(DomainModel):
    """Public view intentionally excludes the protected local storage key."""

    asset_id: UUID
    story_id: UUID
    segment_id: UUID
    script_revision: int
    status: VisualDiscoveryStatus
    candidate: CommonsVisualCandidate
    sha256: Annotated[str | None, StringConstraints(pattern=r"^[a-f0-9]{64}$")] = None
    downloaded_size_bytes: int | None = Field(default=None, gt=0)
    probed_duration_ms: int | None = Field(default=None, gt=0)
    review_note: str | None = Field(default=None, max_length=2_000)
    reviewed_at: datetime | None = None
    created_at: datetime


def _host(url: AnyHttpUrl) -> str:
    split = urlsplit(str(url))
    if split.scheme.casefold() != "https":
        return ""
    return (split.hostname or "").casefold()
