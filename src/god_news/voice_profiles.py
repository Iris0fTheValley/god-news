"""Typed, storage-agnostic voice selection contracts.

The TTS adapter deliberately depends on this module rather than on role API
models or a particular database.  A different role manager, a remote voice
catalogue, or a test fixture can therefore supply the same resolver without
changing synthesis orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.enums import SpeechEmotion

EMOTION_REFERENCE_KEYS: tuple[SpeechEmotion, ...] = tuple(SpeechEmotion)


def normalize_speech_emotion(value: SpeechEmotion | str) -> SpeechEmotion | None:
    """Return a concrete supported emotion without guessing arbitrary labels."""

    if isinstance(value, SpeechEmotion):
        return value
    try:
        return SpeechEmotion(value.strip().casefold())
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class VoiceReference:
    """One reference recording and its spoken transcript."""

    audio_path: Path
    text: str


@dataclass(frozen=True, slots=True)
class ResolvedVoiceProfile:
    """The runtime-only voice configuration selected for one speaker.

    Paths are intentionally unresolved here.  The synthesizer owns trust-root
    and file-type checks immediately before launching a local subprocess.
    """

    profile_id: UUID
    speaker_id: str
    model_profile: str
    gpt_weights_path: Path
    sovits_weights_path: Path
    emotion_refs: Mapping[SpeechEmotion, VoiceReference]
    default_emotion: SpeechEmotion
    # DSakiko stores this once per character (rather than once per emotion).
    # ``None`` intentionally means "use the deployment's legacy default" so
    # existing profiles remain valid while an imported profile can preserve its
    # own Japanese/Chinese/etc. reference transcript language.
    reference_language: str | None = None

    def reference_for(self, emotion: SpeechEmotion | str) -> tuple[SpeechEmotion, VoiceReference]:
        selected = normalize_speech_emotion(emotion) or self.default_emotion
        reference = self.emotion_refs.get(selected)
        if reference is None:
            raise ValueError(f"Voice profile has no reference for emotion '{selected.value}'.")
        return selected, reference


class VoiceProfileResolver(Protocol):
    """Looks up a currently-enabled, synthesis-capable voice by speaker id."""

    async def resolve_voice(self, speaker_id: str) -> ResolvedVoiceProfile | None: ...
