from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.errors import GodNewsError


class VideoBatchNotFoundError(GodNewsError):
    def __init__(self, batch_id: UUID) -> None:
        super().__init__(
            "video_batch_not_found",
            f"Video batch {batch_id} was not found.",
            status_code=404,
        )


class VideoBatchConflictError(GodNewsError):
    def __init__(self, message: str) -> None:
        super().__init__("video_batch_conflict", message, status_code=409)


class VideoStoryUnavailableError(GodNewsError):
    def __init__(self, story_ids: Sequence[UUID]) -> None:
        joined = ", ".join(str(item) for item in sorted(story_ids, key=str))
        super().__init__(
            "video_story_unavailable",
            f"Stories are already reserved or used by another video batch: {joined}",
            status_code=409,
        )


class NoVideoCandidatesError(GodNewsError):
    def __init__(self) -> None:
        super().__init__(
            "no_video_candidates",
            "No eligible, unused DONE stories are available for a video batch.",
            status_code=409,
        )


class BgmTrackNotFoundError(GodNewsError):
    def __init__(self, track_id: str) -> None:
        super().__init__(
            "bgm_track_not_found",
            f"Local BGM track {track_id} was not found.",
            status_code=404,
        )


class VideoRenderingError(GodNewsError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(
            "video_render_failed",
            message,
            status_code=502,
            retryable=retryable,
        )


class VideoNarrationSynthesisError(GodNewsError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(
            "video_narration_synthesis_failed",
            message,
            status_code=502,
            retryable=retryable,
        )


class VideoRendererUnavailableError(GodNewsError):
    def __init__(self, message: str) -> None:
        super().__init__("video_renderer_unavailable", message, status_code=503)
