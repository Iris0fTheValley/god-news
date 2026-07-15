from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from god_news.domain.enums import SpeechEmotion
from god_news.voice_profiles import EMOTION_REFERENCE_KEYS, ResolvedVoiceProfile, VoiceReference

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

def _validate_asset_ref(value: str) -> str:
    """Keep asset references inert until a dedicated resolver owns them.

    A role profile stores references only; it never opens a local file or fetches
    a URL.  Rejecting control characters and parent-directory traversal makes
    the value safe to persist, log, and eventually hand to a resolver without
    silently changing an operator-provided Windows or POSIX path.
    """

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("asset references cannot contain control characters")
    if any(segment == ".." for segment in value.replace("\\", "/").split("/")):
        raise ValueError("asset references cannot contain parent-directory traversal")
    return value


AssetRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
    AfterValidator(_validate_asset_ref),
]
RoleSlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$",
    ),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class OperationsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoleKind(StrEnum):
    NARRATOR = "narrator"
    HOST = "host"


class DifferentialArtAsset(OperationsModel):
    """One expression/pose in a differential-art character set."""

    state_id: NonBlankStr
    asset_ref: AssetRef
    emotion: NonBlankStr | None = None


class RoleVisualAssets(OperationsModel):
    """Renderer-neutral character asset references.

    References are identifiers only. Resolving and reading an asset belongs to a
    future renderer adapter, so the profile service never guesses a filesystem
    or URL contract.
    """

    live2d_asset_ref: AssetRef | None = None
    differential_art: list[DifferentialArtAsset] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_unique_states(self) -> RoleVisualAssets:
        states = [asset.state_id for asset in self.differential_art]
        if len(states) != len(set(states)):
            raise ValueError("differential art state_id values must be unique")
        return self


class EmotionReference(OperationsModel):
    """DSakiko-compatible reference material for one concrete emotion.

    The JSON shape deliberately mirrors ``reference_audio_and_text.json``:
    ``{"audio_path": "...", "text": "..."}``. Paths remain inert profile
    metadata here; the TTS adapter validates them against configured trusted
    local roots immediately before use.
    """

    audio_path: AssetRef
    text: NonBlankStr


class RoleProfileInput(OperationsModel):
    """Editable role fields shared by create, replace, and stored profiles.

    ``tts_enabled`` is an explicit operational opt-in. Existing rows may carry
    legacy weight metadata without seven emotion references; they remain valid
    non-TTS profiles until an operator completes the configuration and enables
    synthesis. This avoids silently treating old metadata as a live subprocess
    configuration.
    """

    slug: RoleSlug
    display_name: NonBlankStr
    kind: RoleKind
    speaker_id: NonBlankStr
    character_prompt: str = Field(default="", max_length=12_000)
    default_emotion: NonBlankStr = "neutral"
    default_spoken_language: NonBlankStr = "zh-CN"
    default_speed: float = Field(default=1.0, ge=0.6, le=1.65)
    default_pitch: float = Field(default=0.0, ge=-12.0, le=12.0)
    gpt_weights_path: AssetRef | None = None
    sovits_weights_path: AssetRef | None = None
    tts_model_profile: NonBlankStr | None = None
    reference_language: NonBlankStr | None = None
    emotion_refs: dict[SpeechEmotion, EmotionReference] = Field(default_factory=dict)
    tts_enabled: bool = False
    visual_assets: RoleVisualAssets = Field(default_factory=RoleVisualAssets)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_tts_configuration(self) -> RoleProfileInput:
        """Require a complete, concrete voice only when it is enabled for TTS."""

        if not self.tts_enabled:
            return self
        if self.gpt_weights_path is None or self.sovits_weights_path is None:
            raise ValueError(
                "TTS-enabled roles require both gpt_weights_path and sovits_weights_path."
            )
        if self.tts_model_profile is None:
            raise ValueError("TTS-enabled roles require tts_model_profile.")
        expected = set(EMOTION_REFERENCE_KEYS)
        actual = set(self.emotion_refs)
        if actual != expected:
            missing = sorted(item.value for item in expected - actual)
            unexpected = sorted(
                item.value if isinstance(item, SpeechEmotion) else str(item)
                for item in actual - expected
            )
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected: {', '.join(unexpected)}")
            raise ValueError(
                "TTS-enabled roles require exactly seven emotion_refs "
                f"({'; '.join(details) or 'invalid keys'})."
            )
        if self.default_emotion not in {item.value for item in SpeechEmotion}:
            raise ValueError(
                "TTS-enabled role default_emotion must be one of the seven supported emotions."
            )
        return self


class RoleProfileCreate(RoleProfileInput):
    pass


class RoleProfileReplace(RoleProfileCreate):
    expected_version: int = Field(ge=1)


class RoleProfile(RoleProfileInput):
    profile_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def as_resolved_voice_profile(self) -> ResolvedVoiceProfile | None:
        """Adapt a stored profile to the TTS-facing, UI-independent contract."""

        if not self.enabled or not self.tts_enabled:
            return None
        if (
            self.gpt_weights_path is None
            or self.sovits_weights_path is None
            or self.tts_model_profile is None
        ):
            return None
        return ResolvedVoiceProfile(
            profile_id=self.profile_id,
            speaker_id=self.speaker_id,
            model_profile=self.tts_model_profile,
            gpt_weights_path=Path(self.gpt_weights_path),
            sovits_weights_path=Path(self.sovits_weights_path),
            emotion_refs={
                emotion: VoiceReference(
                    audio_path=Path(reference.audio_path),
                    text=reference.text,
                )
                for emotion, reference in self.emotion_refs.items()
            },
            default_emotion=SpeechEmotion(self.default_emotion),
            reference_language=self.reference_language,
        )


class RoleProfileDelete(OperationsModel):
    expected_version: int = Field(ge=1)


class OperationKind(StrEnum):
    RETENTION_CLEANUP = "retention_cleanup"


class TriggerOrigin(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"


class OperationRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RetentionArtifactKind(StrEnum):
    MEDIA = "media"
    UPLOADED_MP4 = "uploaded_mp4"


class RetentionAction(StrEnum):
    WOULD_DELETE = "would_delete"
    DELETED = "deleted"
    SKIPPED = "skipped"
    FAILED = "failed"


class RetentionCleanupCommand(OperationsModel):
    operation: Literal[OperationKind.RETENTION_CLEANUP] = OperationKind.RETENTION_CLEANUP
    dry_run: bool = True
    requested_by: NonBlankStr


OperationCommand = RetentionCleanupCommand


class RetentionItemResult(OperationsModel):
    artifact_kind: RetentionArtifactKind
    relative_path: NonBlankStr
    modified_at: datetime | None = None
    size_bytes: int = Field(default=0, ge=0)
    action: RetentionAction
    reason: NonBlankStr | None = None

    @field_validator("modified_at")
    @classmethod
    def normalize_modified_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("modified_at must be timezone-aware")
        return value.astimezone(UTC)


class RetentionCleanupReport(OperationsModel):
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    eligible_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    reclaimed_bytes: int = Field(ge=0)
    items: list[RetentionItemResult]

    @field_validator("started_at", "finished_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retention timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_aggregates(self) -> RetentionCleanupReport:
        eligible_actions = {RetentionAction.WOULD_DELETE, RetentionAction.DELETED}
        eligible = sum(item.action in eligible_actions for item in self.items)
        deleted = sum(item.action is RetentionAction.DELETED for item in self.items)
        failed = sum(item.action is RetentionAction.FAILED for item in self.items)
        if self.eligible_count != eligible:
            raise ValueError("eligible_count does not match item actions")
        if self.deleted_count != deleted:
            raise ValueError("deleted_count does not match item actions")
        if self.failed_count != failed:
            raise ValueError("failed_count does not match item actions")
        if self.dry_run and self.deleted_count:
            raise ValueError("a dry run cannot report deleted files")
        return self


OperationResult = RetentionCleanupReport


class OperationRun(OperationsModel):
    run_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    operation: OperationKind
    origin: TriggerOrigin
    requested_by: NonBlankStr
    schedule_id: NonBlankStr | None = None
    status: OperationRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    result: OperationResult | None = None
    error: NonBlankStr | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def normalize_run_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("operation timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_terminal_state(self) -> OperationRun:
        if self.origin is TriggerOrigin.SCHEDULE and self.schedule_id is None:
            raise ValueError("scheduled operation runs require schedule_id")
        if self.origin is TriggerOrigin.MANUAL and self.schedule_id is not None:
            raise ValueError("manual operation runs cannot have schedule_id")
        if self.status is OperationRunStatus.RUNNING:
            if self.finished_at is not None or self.result is not None or self.error is not None:
                raise ValueError("running operation cannot have terminal fields")
        elif self.finished_at is None:
            raise ValueError("terminal operation run requires finished_at")
        elif self.status is OperationRunStatus.SUCCEEDED:
            if self.result is None or self.error is not None:
                raise ValueError("successful operation requires only a result")
        elif self.result is not None or self.error is None:
            raise ValueError("failed operation requires only an error")
        return self


class ScheduleSnapshot(OperationsModel):
    schedule_id: NonBlankStr
    operation: OperationKind
    enabled: bool
    interval_seconds: float = Field(gt=0)
    next_run_at: datetime | None = None
    last_run_id: UUID | None = None
    last_run_status: OperationRunStatus | None = None

    @field_validator("next_run_at")
    @classmethod
    def normalize_next_run(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("schedule timestamps must be timezone-aware")
        return value.astimezone(UTC)
