from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from god_news.operations.errors import RoleProfileConflictError
from god_news.operations.models import (
    RoleProfile,
    RoleProfileCreate,
    RoleProfileReplace,
    utc_now,
)
from god_news.operations.ports import LiveScriptRoleUsageGuard, RoleProfileRepository
from god_news.voice_profiles import ResolvedVoiceProfile


class RoleProfileService:
    """Application service for versioned narrator/host profiles."""

    def __init__(
        self,
        repository: RoleProfileRepository,
        live_script_usage_guard: LiveScriptRoleUsageGuard | None = None,
    ) -> None:
        self._repository = repository
        self._live_script_usage_guard = live_script_usage_guard

    async def create(self, request: RoleProfileCreate) -> RoleProfile:
        now = utc_now()
        profile = RoleProfile(
            **request.model_dump(),
            created_at=now,
            updated_at=now,
        )
        await self._ensure_new_voice_contract_is_not_live(profile)
        return await self._repository.create(profile)

    async def get(self, profile_id: UUID) -> RoleProfile:
        return await self._repository.get(profile_id)

    async def list(self, *, enabled: bool | None = None) -> Sequence[RoleProfile]:
        return await self._repository.list(enabled=enabled)

    async def get_enabled_by_speaker_id(self, speaker_id: str) -> RoleProfile | None:
        """Return the one enabled profile currently owning ``speaker_id``."""

        return await self._repository.get_enabled_by_speaker_id(speaker_id)

    async def resolve_voice(self, speaker_id: str) -> ResolvedVoiceProfile | None:
        """Expose a narrow TTS contract without coupling synthesis to role APIs."""

        profile = await self.get_enabled_by_speaker_id(speaker_id)
        return None if profile is None else profile.as_resolved_voice_profile()

    async def replace(self, profile_id: UUID, request: RoleProfileReplace) -> RoleProfile:
        current = await self._repository.get(profile_id)
        if current.version != request.expected_version:
            raise RoleProfileConflictError()
        if request.slug != current.slug:
            raise RoleProfileConflictError("Role profile slug is immutable after creation.")
        values = request.model_dump(exclude={"expected_version"})
        # Preserve the durable URL/selector even if a future caller constructs a
        # replacement model by merging stale fields.
        values["slug"] = current.slug
        replacement = RoleProfile(
            profile_id=current.profile_id,
            **values,
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        await self._ensure_voice_contract_is_mutable(current, replacement)
        return await self._repository.replace(
            replacement,
            expected_version=request.expected_version,
        )

    async def delete(self, profile_id: UUID, *, expected_version: int) -> RoleProfile:
        """Soft-disable a role while retaining its historical configuration.

        The HTTP operation keeps its DELETE spelling, but profiles may be
        referenced by already-produced scripts and manifests.  We therefore
        retain the row and perform the state change through the same atomic
        versioned replacement path used by edits.
        """

        current = await self._repository.get(profile_id)
        if current.version != expected_version:
            raise RoleProfileConflictError()
        if not current.enabled:
            return current
        disabled = current.model_copy(
            update={
                "enabled": False,
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        await self._ensure_voice_contract_is_mutable(current, disabled)
        return await self._repository.replace(disabled, expected_version=expected_version)

    async def _ensure_voice_contract_is_mutable(
        self,
        current: RoleProfile,
        replacement: RoleProfile,
    ) -> None:
        """Protect authored-but-unrendered scripts from mutable voice lookup.

        Scripts intentionally persist ``speaker_id`` rather than a database
        role revision. Until an immutable voice snapshot is added to the script
        schema, an enabled TTS profile referenced by a live script must not be
        disabled or have its synthesis-selection fields changed underneath it.
        Editorial fields remain freely editable.
        """

        if self._live_script_usage_guard is None:
            return
        selection_fields = (
            "speaker_id",
            "enabled",
            "tts_enabled",
            "gpt_weights_path",
            "sovits_weights_path",
            "tts_model_profile",
            "reference_language",
            "emotion_refs",
            "default_emotion",
        )
        selection_changed = not all(
            getattr(current, field) == getattr(replacement, field)
            for field in selection_fields
        )
        current_is_voice = current.enabled and current.tts_enabled
        replacement_is_voice = replacement.enabled and replacement.tts_enabled
        if not selection_changed and current_is_voice == replacement_is_voice:
            return

        speaker_ids: list[str] = []
        if current_is_voice and selection_changed:
            speaker_ids.append(current.speaker_id)
        if replacement_is_voice and (
            not current_is_voice or replacement.speaker_id != current.speaker_id
        ):
            speaker_ids.append(replacement.speaker_id)
        for speaker_id in dict.fromkeys(speaker_ids):
            await self._ensure_speaker_not_referenced_by_live_script(speaker_id)

    async def _ensure_new_voice_contract_is_not_live(self, profile: RoleProfile) -> None:
        """Do not let a newly enabled role retarget an existing live script."""

        if profile.enabled and profile.tts_enabled:
            await self._ensure_speaker_not_referenced_by_live_script(profile.speaker_id)

    async def _ensure_speaker_not_referenced_by_live_script(self, speaker_id: str) -> None:
        guard = self._live_script_usage_guard
        if guard is None:
            return
        try:
            is_referenced = await guard.has_live_script_reference(speaker_id)
        except RoleProfileConflictError:
            raise
        except Exception as exc:
            # Fail closed: accepting an uncertain mutation would make an
            # already-reviewed script non-deterministic or unsynthesizable.
            raise RoleProfileConflictError(
                "Unable to verify whether this role is referenced by a live script."
            ) from exc
        if is_referenced:
            raise RoleProfileConflictError(
                "Cannot activate, change, or disable this role's voice "
                "configuration while live scripts reference its speaker_id. "
                "Render or archive those scripts first."
            )
