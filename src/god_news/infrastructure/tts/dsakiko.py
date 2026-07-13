"""Explicit, read-only import support for DSakiko emotion reference JSON.

DSakiko resolves paths in ``reference_audio_and_text.json`` from its
``GPT_SoVITS`` working directory rather than from the JSON file's directory.
This helper preserves that convention and returns absolute paths suitable for
the role-profile API. It never scans a directory or writes back to DSakiko.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from god_news.domain.enums import SpeechEmotion
from god_news.errors import ConfigurationError
from god_news.operations.models import EmotionReference
from god_news.voice_profiles import EMOTION_REFERENCE_KEYS

# DSakiko's own ``character.py`` maps these persisted menu indexes to its
# GPT-SoVITS v2 API language codes. Keep the mapping explicit and fail closed
# for unknown values instead of silently falling back to a deployment default.
_DSAKIKO_REFERENCE_LANGUAGE_CODES = {
    "1": "all_zh",
    "2": "en",
    "3": "all_ja",
    "4": "all_yue",
    "5": "all_ko",
    "6": "zh",
    "7": "ja",
    "8": "yue",
    "9": "ko",
    "10": "auto",
    "11": "auto_yue",
}
_DSAKIKO_REFERENCE_LANGUAGE_LABELS = {
    "中文": "all_zh",
    "英文": "en",
    "日文": "all_ja",
    "粤语": "all_yue",
    "韩文": "all_ko",
    "中英混合": "zh",
    "日英混合": "ja",
    "粤英混合": "yue",
    "韩英混合": "ko",
    "多语种混合": "auto",
    "多语种混合(粤语)": "auto_yue",
}
_GPT_SOVITS_LANGUAGE_CODES = frozenset(_DSAKIKO_REFERENCE_LANGUAGE_CODES.values())


@dataclass(frozen=True, slots=True)
class DSakikoVoiceAssets:
    """Explicitly imported DSakiko reference assets for one role profile."""

    emotion_refs: dict[SpeechEmotion, EmotionReference]
    reference_language: str


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def load_dsakiko_emotion_refs(
    *,
    config_path: Path,
    dsakiko_root: Path,
    working_directory: Path | None = None,
) -> dict[SpeechEmotion, EmotionReference]:
    """Load one DSakiko ``reference_audio_and_text.json`` without mutation.

    ``working_directory`` defaults to ``<dsakiko_root>/GPT_SoVITS`` because
    that is the path base used by DSakiko's own character loader. The returned
    paths are absolute, so they can be persisted without retaining an implicit
    current-directory dependency.
    """

    try:
        root = dsakiko_root.expanduser().resolve(strict=True)
        config = config_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError("DSakiko root or reference JSON does not exist.") from exc
    if not root.is_dir() or not config.is_file() or not _within(config, root):
        raise ConfigurationError("DSakiko reference JSON must be a file inside its root.")
    base = (working_directory or root / "GPT_SoVITS").expanduser().resolve(strict=False)
    if not _within(base, root):
        raise ConfigurationError("DSakiko working directory must stay inside its root.")
    try:
        loaded: Any = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("DSakiko reference JSON could not be read.") from exc
    raw_refs = loaded.get("emotion_refs") if isinstance(loaded, dict) else None
    if not isinstance(raw_refs, dict):
        raise ConfigurationError("DSakiko reference JSON is missing an emotion_refs mapping.")

    refs: dict[SpeechEmotion, EmotionReference] = {}
    for raw_emotion, raw_reference in raw_refs.items():
        try:
            emotion = SpeechEmotion(str(raw_emotion).strip().casefold())
        except ValueError as exc:
            raise ConfigurationError(
                "DSakiko reference JSON contains an unsupported emotion."
            ) from exc
        if not isinstance(raw_reference, dict):
            raise ConfigurationError("DSakiko emotion reference must be an object.")
        raw_audio = raw_reference.get("audio_path")
        raw_text = raw_reference.get("text")
        if not isinstance(raw_audio, str) or not isinstance(raw_text, str):
            raise ConfigurationError(
                "DSakiko emotion reference requires audio_path and text strings."
            )
        candidate = Path(raw_audio).expanduser()
        absolute_audio = candidate if candidate.is_absolute() else base / candidate
        try:
            audio = absolute_audio.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError("DSakiko emotion reference audio does not exist.") from exc
        if not audio.is_file() or not _within(audio, root):
            raise ConfigurationError("DSakiko emotion reference audio is outside its root.")
        refs[emotion] = EmotionReference(audio_path=str(audio), text=raw_text)

    if set(refs) != set(EMOTION_REFERENCE_KEYS):
        raise ConfigurationError("DSakiko reference JSON must define exactly seven emotions.")
    return refs


def load_dsakiko_reference_language(
    *,
    config_path: Path,
    dsakiko_root: Path,
) -> str:
    """Read DSakiko's adjacent ``reference_audio_language.txt`` explicitly.

    The upstream program persists either a menu index (for example ``3``) or a
    Chinese menu label. This adapter returns the exact GPT-SoVITS API code
    (``all_ja`` for ``3``) so a role does not accidentally use the deployment's
    unrelated global prompt-language setting.
    """

    try:
        root = dsakiko_root.expanduser().resolve(strict=True)
        config = config_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError("DSakiko root or reference JSON does not exist.") from exc
    if not root.is_dir() or not config.is_file() or not _within(config, root):
        raise ConfigurationError("DSakiko reference JSON must be a file inside its root.")
    language_file = config.parent / "reference_audio_language.txt"
    try:
        language = language_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("DSakiko reference language file could not be read.") from exc
    for raw_line in language.splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        code = _DSAKIKO_REFERENCE_LANGUAGE_CODES.get(value)
        if code is None:
            code = _DSAKIKO_REFERENCE_LANGUAGE_LABELS.get(value)
        if code is None and value.casefold() in _GPT_SOVITS_LANGUAGE_CODES:
            code = value.casefold()
        if code is None:
            raise ConfigurationError("DSakiko reference language value is unsupported.")
        return code
    raise ConfigurationError("DSakiko reference language file contains no usable value.")


def load_dsakiko_voice_assets(
    *,
    config_path: Path,
    dsakiko_root: Path,
    working_directory: Path | None = None,
) -> DSakikoVoiceAssets:
    """Import the complete role-level DSakiko reference configuration.

    This is intentionally an operator-invoked read-only import. It does not
    scan folders, choose weights by filename, or mutate the source installation.
    """

    return DSakikoVoiceAssets(
        emotion_refs=load_dsakiko_emotion_refs(
            config_path=config_path,
            dsakiko_root=dsakiko_root,
            working_directory=working_directory,
        ),
        reference_language=load_dsakiko_reference_language(
            config_path=config_path,
            dsakiko_root=dsakiko_root,
        ),
    )
