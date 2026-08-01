from __future__ import annotations

from typing import Protocol

from god_news.domain.video import TemplateDefinition
from god_news.domain.video_registry import VideoCapabilityPolicy


class VideoCapabilityPolicyRepository(Protocol):
    async def get(self, key: str) -> VideoCapabilityPolicy: ...

    async def list(self) -> dict[str, VideoCapabilityPolicy]: ...

    async def set(
        self,
        *,
        key: str,
        enabled_for_new_batches: bool,
        expected_version: int,
        reason: str,
        operator_id: str,
    ) -> VideoCapabilityPolicy: ...


class EffectiveVideoTemplateResolver(Protocol):
    async def resolve_template_for_new_batch(
        self,
        template_id: str,
        template_version: str,
    ) -> TemplateDefinition: ...
