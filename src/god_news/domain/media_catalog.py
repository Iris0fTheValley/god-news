from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from god_news.domain.models import DomainModel, NonBlankStr


class MediaCatalogSourceKind(StrEnum):
    VISUAL_ASSET = "visual_asset"
    VISUAL_DISCOVERY = "visual_discovery"
    SOURCE_MEDIA = "source_media"


class MediaCatalogKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class MediaCatalogLifecycle(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MediaUsagePurpose(StrEnum):
    STORY_SEGMENT = "story_segment"
    STORY_EVIDENCE = "story_evidence"
    BATCH_SCENE = "batch_scene"


class MediaUsageState(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


CatalogId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(visual_asset|visual_discovery|source_media):[0-9a-f-]{36}$",
    ),
]


class MediaAssetUsage(DomainModel):
    purpose: MediaUsagePurpose
    state: MediaUsageState
    story_id: UUID
    segment_id: UUID | None = None
    script_revision: int | None = Field(default=None, ge=1)
    batch_id: UUID | None = None
    scene_sequence: int | None = Field(default=None, ge=0)
    batch_version: int | None = Field(default=None, ge=1)
    render_input_sha256: str | None = None


class MediaCatalogEntry(DomainModel):
    catalog_id: CatalogId
    source_kind: MediaCatalogSourceKind
    source_asset_id: UUID
    media_kind: MediaCatalogKind
    lifecycle: MediaCatalogLifecycle
    lifecycle_version: int = Field(ge=1)
    story_id: UUID
    segment_id: UUID | None = None
    script_revision: int | None = Field(default=None, ge=1)
    filename: NonBlankStr
    mime_type: NonBlankStr
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    source_url: str | None = None
    external_preview_url: str | None = None
    has_local_content: bool
    attribution: str | None = None
    license_label: str | None = None
    editorial_state: NonBlankStr
    publish_eligible: bool
    selectable: bool
    reusable: bool
    archived_at: datetime | None = None
    archived_by: str | None = None
    archive_reason: str | None = None
    usages: list[MediaAssetUsage] = Field(default_factory=list, max_length=100)


class MediaCatalogPage(DomainModel):
    items: list[MediaCatalogEntry]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class ChangeMediaLifecycleRequest(DomainModel):
    expected_version: int = Field(ge=1)
    operator_id: NonBlankStr
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


def make_catalog_id(source_kind: MediaCatalogSourceKind, source_asset_id: UUID) -> str:
    return f"{source_kind.value}:{source_asset_id}"
