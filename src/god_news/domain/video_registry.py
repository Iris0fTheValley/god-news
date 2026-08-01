from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from god_news.domain.models import DomainModel, NonBlankStr
from god_news.domain.video import EpisodeHostSlot, VideoOutputProfileId


class VideoCapabilityKind(StrEnum):
    TEMPLATE = "template"
    MODULE = "module"
    VARIANT = "variant"
    PRESET = "preset"


CapabilityKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(template|module|variant|preset):[A-Za-z0-9_.:@-]+$",
    ),
]


class VideoCapabilityPolicy(DomainModel):
    key: CapabilityKey
    enabled_for_new_batches: bool = True
    version: int = Field(default=1, ge=1)
    reason: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class VideoCapabilityView(DomainModel):
    key: CapabilityKey
    kind: VideoCapabilityKind
    display_name: NonBlankStr
    registered: bool = True
    configurable: bool
    policy: VideoCapabilityPolicy
    effective_enabled: bool
    disabled_by: list[CapabilityKey] = Field(default_factory=list)
    dependencies: list[CapabilityKey] = Field(default_factory=list)
    used_by: list[CapabilityKey] = Field(default_factory=list)
    supported_profiles: list[VideoOutputProfileId] = Field(default_factory=list)
    supported_host_slots: list[EpisodeHostSlot] = Field(default_factory=list)
    active_batch_ids: list[str] = Field(default_factory=list, max_length=20)
    usage_count: int = Field(default=0, ge=0)


class VideoRegistryView(DomainModel):
    capabilities: list[VideoCapabilityView]


class SetVideoCapabilityPolicy(DomainModel):
    key: CapabilityKey
    enabled_for_new_batches: bool
    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    operator_id: NonBlankStr

    @model_validator(mode="after")
    def require_configurable_kind(self) -> SetVideoCapabilityPolicy:
        if self.key.startswith("preset:"):
            raise ValueError("renderer presets are read-only capabilities")
        return self
