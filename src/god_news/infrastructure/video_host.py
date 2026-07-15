from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.domain.models import Story
from god_news.domain.video import (
    HostVisualReservations,
    RemotionVideoProps,
    VideoInputAsset,
    VideoRenderArtifact,
)
from god_news.video_errors import VideoRendererUnavailableError


class PlaceholderHostRenderer:
    @property
    def name(self) -> str:
        return "placeholder"

    async def prepare(self, stories: Sequence[Story]) -> HostVisualReservations:
        if not stories:
            raise ValueError("host preparation requires at least one story")
        return HostVisualReservations(renderer="placeholder")


class UnavailableBatchVideoRenderer:
    """Safe production default until a local Remotion process adapter is enabled."""

    @property
    def name(self) -> str:
        return "unavailable"

    async def render(
        self,
        batch_id: UUID,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> VideoRenderArtifact:
        del batch_id, props, input_assets
        raise VideoRendererUnavailableError(
            "No local batch VideoRenderer is configured; the reviewed manifest remains retryable."
        )

    async def cleanup_interrupted(self, batch_ids: Sequence[UUID]) -> int:
        del batch_ids
        return 0
