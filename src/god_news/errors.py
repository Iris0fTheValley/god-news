from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class GodNewsError(Exception):
    code: str
    public_message: str
    status_code: int = 500
    story_id: UUID | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return self.public_message


class ConfigurationError(GodNewsError):
    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message, status_code=503)


class StoryNotFoundError(GodNewsError):
    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "story_not_found",
            "Story was not found.",
            status_code=404,
            story_id=story_id,
        )


class InvalidTransitionError(GodNewsError):
    def __init__(self, story_id: UUID, current: str, target: str) -> None:
        super().__init__(
            "invalid_story_transition",
            f"Story cannot transition from {current} to {target}.",
            status_code=409,
            story_id=story_id,
        )


class ConcurrentWriteError(GodNewsError):
    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "concurrent_story_write",
            "Story changed concurrently; reload it and retry.",
            status_code=409,
            story_id=story_id,
            retryable=True,
        )


class DuplicateStoryError(GodNewsError):
    def __init__(self, existing_story_id: UUID, matched_by: str) -> None:
        super().__init__(
            "duplicate_story",
            f"A story with the same {matched_by} already exists.",
            status_code=409,
            story_id=existing_story_id,
        )


class StoryInvariantError(GodNewsError):
    def __init__(self, story_id: UUID, message: str) -> None:
        super().__init__(
            "story_invariant_violated",
            message,
            status_code=409,
            story_id=story_id,
        )


class VoiceProfileResolutionError(GodNewsError):
    """The voice catalogue could not be consulted at an approval boundary."""

    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "voice_profile_resolution_failed",
            "Could not verify the selected narrator role. Retry when role profiles are available.",
            status_code=503,
            story_id=story_id,
            retryable=True,
        )


class IdempotencyConflictError(GodNewsError):
    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "idempotency_conflict",
            "The review_id was already used for a different request.",
            status_code=409,
            story_id=story_id,
        )


class FetchError(GodNewsError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__("fetch_failed", message, status_code=502, retryable=retryable)


class FetchPolicyError(GodNewsError):
    def __init__(self, message: str) -> None:
        super().__init__("source_url_rejected", message, status_code=422, retryable=False)


class LLMGenerationError(GodNewsError):
    def __init__(
        self,
        message: str,
        story_id: UUID | None = None,
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(
            "llm_generation_failed",
            message,
            status_code=502,
            story_id=story_id,
            retryable=retryable,
        )


class TTSGenerationError(GodNewsError):
    def __init__(self, message: str, story_id: UUID | None = None) -> None:
        super().__init__(
            "tts_generation_failed",
            message,
            status_code=502,
            story_id=story_id,
            retryable=True,
        )


class ArtifactNotReadyError(GodNewsError):
    def __init__(self, story_id: UUID, message: str) -> None:
        super().__init__(
            "artifact_not_ready",
            message,
            status_code=409,
            story_id=story_id,
        )


class VisualAssetNotFoundError(GodNewsError):
    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "visual_asset_not_found",
            "Visual asset was not found for this story.",
            status_code=404,
            story_id=story_id,
        )


class VisualAssetUploadError(GodNewsError):
    def __init__(self, story_id: UUID, message: str, *, status_code: int = 422) -> None:
        super().__init__(
            "visual_asset_rejected",
            message,
            status_code=status_code,
            story_id=story_id,
        )


class VisualAssetStorageError(GodNewsError):
    def __init__(self, story_id: UUID, message: str = "Visual asset could not be stored.") -> None:
        super().__init__(
            "visual_asset_storage_failed",
            message,
            status_code=500,
            story_id=story_id,
            retryable=True,
        )


class SourceMediaAcquisitionError(GodNewsError):
    def __init__(
        self,
        story_id: UUID,
        message: str,
        *,
        status_code: int = 422,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            "source_media_acquisition_failed",
            message,
            status_code=status_code,
            story_id=story_id,
            retryable=retryable,
        )


class SourceTranscriptionNotFoundError(GodNewsError):
    def __init__(self, transcription_id: UUID) -> None:
        super().__init__(
            "source_transcription_not_found",
            "Source-media transcription was not found.",
            status_code=404,
        )
        self.transcription_id = transcription_id


class ConcurrentSourceTranscriptionWriteError(GodNewsError):
    def __init__(self, story_id: UUID) -> None:
        super().__init__(
            "concurrent_source_transcription_write",
            "Source-media transcription changed concurrently; reload and retry.",
            status_code=409,
            story_id=story_id,
            retryable=True,
        )


class SourceTranscriptionOperationError(GodNewsError):
    def __init__(
        self,
        story_id: UUID,
        message: str,
        *,
        status_code: int = 409,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            "source_transcription_operation_failed",
            message,
            status_code=status_code,
            story_id=story_id,
            retryable=retryable,
        )
