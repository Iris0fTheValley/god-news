from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, model_validator

from god_news.domain.models import DomainModel, NonBlankStr, utc_now


class VisualAssetOrigin(StrEnum):
    """Where a visual asset came from, without overloading editorial hints."""

    EDITOR_UPLOAD = "editor_upload"
    SOURCE_PAGE_SCREENSHOT = "source_page_screenshot"


class ImageContentType(StrEnum):
    """Raster formats accepted by the local visual-asset boundary."""

    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"


Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class VisualAsset(DomainModel):
    """Public, stable reference to a stored raster asset.

    ``storage_key`` deliberately does not appear here.  Clients render this
    reference only through the scoped media endpoint, which keeps local paths
    out of API responses and makes the eventual video-renderer storage adapter
    replaceable.
    """

    asset_id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    segment_id: UUID | None = None
    script_revision: int | None = Field(default=None, ge=1)
    origin: VisualAssetOrigin
    content_type: ImageContentType
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    sha256: Sha256Hex
    size_bytes: int = Field(gt=0)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_binding(self) -> VisualAsset:
        if self.origin is VisualAssetOrigin.EDITOR_UPLOAD:
            if self.segment_id is None or self.script_revision is None:
                raise ValueError("editor uploads must bind to a script segment and revision")
        elif self.segment_id is not None or self.script_revision is not None:
            raise ValueError("source-page screenshots are story-level assets")
        return self


class StoredVisualAsset(VisualAsset):
    """Persistence-only extension containing an opaque, relative storage key."""

    storage_key: NonBlankStr


class SegmentVisualAssetBinding(DomainModel):
    segment_id: UUID
    asset: VisualAsset

    @model_validator(mode="after")
    def validate_matching_segment(self) -> SegmentVisualAssetBinding:
        if self.asset.segment_id != self.segment_id:
            raise ValueError("visual asset binding must match its segment")
        return self


class StoryVisualAssets(DomainModel):
    """Assets effective for one editable script revision.

    ``source_page_url`` is only an operator-facing candidate URL. It is never
    an image URL and never implies a screenshot was captured.  A UI may show a
    default preview only when ``source_page_screenshot`` is non-null.
    """

    story_id: UUID
    story_version: int = Field(ge=1)
    script_revision: int = Field(ge=1)
    source_page_url: str | None = None
    source_page_screenshot: VisualAsset | None = None
    segment_assets: list[SegmentVisualAssetBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_segment_bindings(self) -> StoryVisualAssets:
        segment_ids = [binding.segment_id for binding in self.segment_assets]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("at most one active visual asset is allowed per script segment")
        if self.source_page_screenshot is not None:
            if self.source_page_screenshot.story_id != self.story_id:
                raise ValueError("source-page screenshot belongs to another story")
            if self.source_page_screenshot.origin is not VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT:
                raise ValueError("source-page screenshot must have screenshot origin")
        for binding in self.segment_assets:
            if binding.asset.story_id != self.story_id:
                raise ValueError("segment visual asset belongs to another story")
            if binding.asset.script_revision != self.script_revision:
                raise ValueError("segment visual asset belongs to another script revision")
        return self


class VisualAssetMutation(DomainModel):
    """Successful mutation result with the concurrency version to use next."""

    asset: VisualAsset
    story_version: int = Field(ge=1)


class UploadSegmentVisualAssetRequest(DomainModel):
    """Metadata sent as query parameters alongside a raw raster request body."""

    expected_story_version: int = Field(ge=1)
    expected_script_revision: int = Field(ge=1)
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]


class DeleteSegmentVisualAssetRequest(DomainModel):
    expected_story_version: int = Field(ge=1)
    expected_script_revision: int = Field(ge=1)
