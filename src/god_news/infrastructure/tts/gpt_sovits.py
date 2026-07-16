from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import wave
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import anyio
import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from god_news.domain.enums import AudioFormat, SpeechEmotion
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    ScriptDocument,
    ScriptSegment,
    SegmentSynthesisProvenance,
    SynthesisMetadata,
)
from god_news.errors import ConfigurationError, TTSGenerationError
from god_news.infrastructure.processes import (
    attach_kill_on_close_job,
    close_kill_on_close_job,
    sanitized_subprocess_env,
    terminate_process_tree,
)
from god_news.voice_profiles import (
    EMOTION_REFERENCE_KEYS,
    ResolvedVoiceProfile,
    VoiceProfileResolver,
    VoiceReference,
    normalize_speech_emotion,
)


class _TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    text_lang: str
    ref_audio_path: str
    aux_ref_audio_paths: list[str] = Field(default_factory=list)
    prompt_text: str
    prompt_lang: str
    top_k: int = 5
    top_p: float = 1.0
    temperature: float = 1.0
    text_split_method: str = "cut5"
    batch_size: int = 1
    batch_threshold: float = 0.75
    split_bucket: bool = True
    speed_factor: float
    fragment_interval: float = 0.3
    seed: int
    media_type: Literal["wav"] = "wav"
    streaming_mode: Literal[0] = 0
    parallel_infer: bool = True
    repetition_penalty: float = 1.35


@dataclass(frozen=True, slots=True)
class _WavInfo:
    duration_ms: int
    sample_rate_hz: int
    channels: int


@dataclass(slots=True)
class _ServerProcess:
    process: asyncio.subprocess.Process
    stdout_task: asyncio.Task[None]
    stderr_task: asyncio.Task[None]
    log_tail: deque[str]
    port: int
    job_handle: int | None
    force_shutdown: bool = False
    stop_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True, slots=True)
class _PreparedConfig:
    model_identity: str
    gpt_weights_path: Path
    sovits_weights_path: Path


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    """A content hash tied to the exact file metadata observed around it."""

    path: Path
    size_bytes: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _VoiceRuntime:
    """One isolated GPT-SoVITS server configuration keyed by its weight pair."""

    model_profile: str
    gpt_weights_path: Path | None
    sovits_weights_path: Path | None


@dataclass(frozen=True, slots=True)
class _SegmentVoicePlan:
    """The already-validated voice assets for one script segment."""

    segment: ScriptSegment
    runtime: _VoiceRuntime
    emotion: SpeechEmotion
    reference_audio_path: Path
    reference_text: str
    prompt_language: str


@dataclass(frozen=True, slots=True)
class _ValidatedVoiceProfile:
    runtime: _VoiceRuntime
    default_emotion: SpeechEmotion
    emotion_refs: Mapping[SpeechEmotion, tuple[Path, str]]
    prompt_language: str


@dataclass(frozen=True, slots=True)
class _ActiveRuntime:
    server: _ServerProcess
    prepared: _PreparedConfig
    runtime_config_sha256: str
    gpt_weights_sha256: str
    sovits_weights_sha256: str
    gpt_weights_snapshot: _FileSnapshot
    sovits_weights_snapshot: _FileSnapshot


_PROMPT_LANGUAGES_BY_MODEL_VERSION: Mapping[str, frozenset[str]] = {
    "v1": frozenset({"auto", "en", "zh", "ja", "all_zh", "all_ja"}),
    "v2": frozenset(
        {
            "auto",
            "auto_yue",
            "en",
            "zh",
            "ja",
            "yue",
            "ko",
            "all_zh",
            "all_ja",
            "all_yue",
            "all_ko",
        }
    ),
    "v2Pro": frozenset(
        {
            "auto",
            "auto_yue",
            "en",
            "zh",
            "ja",
            "yue",
            "ko",
            "all_zh",
            "all_ja",
            "all_yue",
            "all_ko",
        }
    ),
    "v2ProPlus": frozenset(
        {
            "auto",
            "auto_yue",
            "en",
            "zh",
            "ja",
            "yue",
            "ko",
            "all_zh",
            "all_ja",
            "all_yue",
            "all_ko",
        }
    ),
    "v3": frozenset(
        {
            "auto",
            "auto_yue",
            "en",
            "zh",
            "ja",
            "yue",
            "ko",
            "all_zh",
            "all_ja",
            "all_yue",
            "all_ko",
        }
    ),
    "v4": frozenset(
        {
            "auto",
            "auto_yue",
            "en",
            "zh",
            "ja",
            "yue",
            "ko",
            "all_zh",
            "all_ja",
            "all_yue",
            "all_ko",
        }
    ),
}


async def _drain_stream(
    stream: asyncio.StreamReader | None,
    log_tail: deque[str],
    prefix: str,
) -> None:
    if stream is None:
        return
    while line := await stream.readline():
        log_tail.append(f"{prefix}: {line.decode('utf-8', errors='replace').rstrip()}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_wav(path: Path) -> _WavInfo:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        channels = handle.getnchannels()
    if frames <= 0 or rate <= 0 or channels <= 0:
        raise ValueError("WAV has invalid stream metadata")
    return _WavInfo(
        duration_ms=max(1, round(frames / rate * 1000)),
        sample_rate_hz=rate,
        channels=channels,
    )


def _choose_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        return False
    return True


def _prepare_runtime_config(
    *,
    source_path: Path,
    destination_path: Path,
    root: Path,
    profile_name: str,
    gpt_weights: Path | None,
    sovits_weights: Path | None,
    device: str,
    use_half_precision: bool,
) -> _PreparedConfig:
    with source_path.open("r", encoding="utf-8") as handle:
        loaded: Any = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("GPT-SoVITS config root must be a mapping")
    profile = loaded.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(f"GPT-SoVITS config has no profile named {profile_name}")
    custom = dict(profile)
    version = custom.get("version")
    if version not in {"v1", "v2", "v2Pro", "v2ProPlus", "v3", "v4"}:
        raise ValueError(f"GPT-SoVITS profile {profile_name} has an invalid version")
    custom["device"] = device
    custom["is_half"] = use_half_precision
    if gpt_weights is not None and sovits_weights is not None:
        custom["t2s_weights_path"] = str(gpt_weights.resolve())
        custom["vits_weights_path"] = str(sovits_weights.resolve())
    for key in (
        "t2s_weights_path",
        "vits_weights_path",
        "bert_base_path",
        "cnhuhbert_base_path",
    ):
        value = custom.get(key)
        if isinstance(value, str) and not Path(value).is_absolute():
            custom[key] = str((root / value).resolve())
    required_paths = {
        "t2s_weights_path": False,
        "vits_weights_path": False,
        "bert_base_path": True,
        "cnhuhbert_base_path": True,
    }
    for key, expect_directory in required_paths.items():
        value = custom.get(key)
        if not isinstance(value, str):
            raise ValueError(f"GPT-SoVITS profile is missing {key}")
        resolved = Path(value)
        if not resolved.exists() or resolved.is_dir() is not expect_directory:
            raise ValueError(f"GPT-SoVITS configured path is invalid: {key}")
    loaded["custom"] = custom
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with destination_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(loaded, handle, allow_unicode=True, sort_keys=False)
    model_identity = (
        f"gpt-sovits:{profile_name}:"
        f"{Path(str(custom['t2s_weights_path'])).name}:"
        f"{Path(str(custom['vits_weights_path'])).name}"
    )
    return _PreparedConfig(
        model_identity=model_identity,
        gpt_weights_path=Path(str(custom["t2s_weights_path"])),
        sovits_weights_path=Path(str(custom["vits_weights_path"])),
    )


def _load_model_profile_version(*, source_path: Path, profile_name: str) -> str:
    """Read only the vendor-declared model version for early API validation."""

    with source_path.open("r", encoding="utf-8") as handle:
        loaded: Any = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("GPT-SoVITS config root must be a mapping")
    profile = loaded.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(f"GPT-SoVITS config has no profile named {profile_name}")
    version = profile.get("version")
    if not isinstance(version, str) or version not in _PROMPT_LANGUAGES_BY_MODEL_VERSION:
        raise ValueError(f"GPT-SoVITS profile {profile_name} has an invalid version")
    return version


class GPTSoVITSSpeechSynthesizer:
    """Starts the vendor API on loopback for one story, then always kills it."""

    def __init__(
        self,
        *,
        root: Path,
        python_executable: Path,
        source_config: Path,
        output_dir: Path,
        reference_audio: Path,
        reference_text_file: Path,
        prompt_language: str,
        text_language: str,
        default_speaker_id: str,
        model_profile: str,
        gpt_weights: Path | None,
        sovits_weights: Path | None,
        device: str,
        use_half_precision: bool,
        startup_timeout_seconds: float,
        request_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        probe_timeout_seconds: float,
        startup_poll_interval_seconds: float,
        force_shutdown_wait_seconds: float,
        process_kill_grace_seconds: float,
        drain_timeout_seconds: float,
        max_audio_bytes: int,
        seed: int,
        top_k: int,
        top_p: float,
        temperature: float,
        text_split_method: str,
        batch_size: int,
        batch_threshold: float,
        fragment_interval: float,
        repetition_penalty: float,
        parallel_infer: bool,
        max_concurrency: int = 1,
        voice_resolver: VoiceProfileResolver | None = None,
        trusted_voice_asset_roots: tuple[Path, ...] = (),
    ) -> None:
        self._root = root.resolve()
        self._python = python_executable.resolve()
        self._source_config = source_config.resolve()
        self._output_dir = output_dir.resolve()
        self._reference_audio = reference_audio.resolve()
        self._reference_text_file = reference_text_file.resolve()
        self._prompt_language = prompt_language.lower()
        self._text_language = text_language.lower()
        self._default_speaker_id = default_speaker_id
        self._model_profile = model_profile
        self._gpt_weights = (
            None if gpt_weights is None else gpt_weights.expanduser().resolve(strict=False)
        )
        self._sovits_weights = (
            None if sovits_weights is None else sovits_weights.expanduser().resolve(strict=False)
        )
        self._device = device
        self._use_half_precision = use_half_precision
        self._startup_timeout = startup_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._probe_timeout = probe_timeout_seconds
        self._startup_poll_interval = startup_poll_interval_seconds
        self._force_shutdown_wait = force_shutdown_wait_seconds
        self._process_kill_grace = process_kill_grace_seconds
        self._drain_timeout = drain_timeout_seconds
        self._max_audio_bytes = max_audio_bytes
        self._seed = seed
        self._top_k = top_k
        self._top_p = top_p
        self._temperature = temperature
        self._text_split_method = text_split_method
        self._batch_size = batch_size
        self._batch_threshold = batch_threshold
        self._fragment_interval = fragment_interval
        self._repetition_penalty = repetition_penalty
        self._parallel_infer = parallel_infer
        self._voice_resolver = voice_resolver
        roots: list[Path] = []
        for candidate in (self._root, *trusted_voice_asset_roots):
            normalized = candidate.expanduser().resolve(strict=False)
            if normalized not in roots:
                roots.append(normalized)
        self._trusted_voice_asset_roots = tuple(roots)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[int, _ServerProcess] = {}
        self._file_hash_cache: dict[tuple[Path, int, int], str] = {}

    async def healthcheck(self) -> None:
        self._validate_paths()
        with tempfile.TemporaryDirectory(prefix="god-news-tts-health-") as temporary:
            await asyncio.to_thread(
                _prepare_runtime_config,
                source_path=self._source_config,
                destination_path=Path(temporary) / "tts_infer.yaml",
                root=self._root,
                profile_name=self._model_profile,
                gpt_weights=self._gpt_weights,
                sovits_weights=self._sovits_weights,
                device=self._device,
                use_half_precision=self._use_half_precision,
        )
        await self._load_legacy_reference()
        await self._validated_prompt_language(
            self._prompt_language,
            model_profile=self._model_profile,
            label="legacy reference",
        )

    async def synthesize(self, story_id: UUID, script: ScriptDocument) -> AudioBundle:
        self._validate_capabilities(script)
        self._validate_paths()
        async with self._semaphore:
            plans = await self._resolve_segment_voice_plans(script)
            return await self._synthesize_exclusive(story_id, script, plans)

    def _validate_paths(self) -> None:
        required = (self._root, self._python, self._root / "api_v2.py", self._source_config)
        if any(not path.exists() for path in required):
            raise ConfigurationError("GPT-SoVITS paths are incomplete or do not exist.")
        if not _within(self._source_config, self._root):
            raise ConfigurationError(
                "GPT-SoVITS runtime config must stay inside its root directory."
            )
        self._require_trusted_file(self._reference_audio, "legacy reference audio")
        self._require_trusted_file(self._reference_text_file, "legacy reference transcript")
        if (self._gpt_weights is None) is not (self._sovits_weights is None):
            raise ConfigurationError("Configured GPT and SoVITS weights must be set as a pair.")
        if self._gpt_weights is not None and self._sovits_weights is not None:
            self._validate_weight_pair(self._gpt_weights, self._sovits_weights)

    def _validate_capabilities(self, script: ScriptDocument) -> None:
        for segment in script.segments:
            if segment.pitch != 0:
                raise TTSGenerationError("GPT-SoVITS does not support pitch control.")

    def _require_trusted_file(self, path: Path, label: str) -> Path:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError(f"Configured {label} does not exist.") from exc
        if not resolved.is_file():
            raise ConfigurationError(f"Configured {label} must be a regular file.")
        if not any(_within(resolved, root) for root in self._trusted_voice_asset_roots):
            raise ConfigurationError(f"Configured {label} is outside trusted local voice roots.")
        return resolved

    def _validate_weight_pair(self, gpt_weights: Path, sovits_weights: Path) -> tuple[Path, Path]:
        gpt = self._require_trusted_file(gpt_weights, "GPT voice weights")
        sovits = self._require_trusted_file(sovits_weights, "SoVITS voice weights")
        if gpt.suffix.casefold() != ".ckpt":
            raise ConfigurationError("GPT voice weights must use a .ckpt file.")
        if sovits.suffix.casefold() != ".pth":
            raise ConfigurationError("SoVITS voice weights must use a .pth file.")
        return gpt, sovits

    async def _validate_reference(
        self,
        reference: VoiceReference,
        *,
        label: str,
    ) -> tuple[Path, str]:
        audio_path = self._require_trusted_file(reference.audio_path, f"{label} audio")
        if audio_path.suffix.casefold() != ".wav":
            raise ConfigurationError(f"{label.capitalize()} audio must be a WAV file.")
        prompt_text = reference.text.strip()
        if not prompt_text:
            raise ConfigurationError(f"{label.capitalize()} transcript is empty.")
        try:
            info = await asyncio.to_thread(_inspect_wav, audio_path)
        except (OSError, ValueError, wave.Error) as exc:
            raise ConfigurationError(f"{label.capitalize()} audio is not a valid WAV.") from exc
        if not 3_000 <= info.duration_ms <= 10_000:
            raise ConfigurationError(f"{label.capitalize()} audio must be 3 to 10 seconds long.")
        return audio_path, prompt_text

    async def _load_legacy_reference(self) -> tuple[Path, str]:
        try:
            prompt_text = await asyncio.to_thread(
                self._reference_text_file.read_text,
                encoding="utf-8",
            )
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError(
                "GPT-SoVITS legacy reference transcript could not be read."
            ) from exc
        return await self._validate_reference(
            VoiceReference(audio_path=self._reference_audio, text=prompt_text),
            label="legacy reference",
        )

    async def _validated_prompt_language(
        self,
        value: str,
        *,
        model_profile: str,
        label: str,
    ) -> str:
        """Normalize and verify a reference transcript language before GPU start.

        GPT-SoVITS validates this at its HTTP boundary, but doing so here means
        an imported DSakiko role cannot spend GPU startup time only to fail an
        avoidable request. The accepted set is selected from the vendor YAML's
        declared model version rather than inferred from profile naming.
        """

        language = value.strip().casefold()
        if not language:
            raise ConfigurationError(f"Configured {label} language is blank.")
        try:
            version = await asyncio.to_thread(
                _load_model_profile_version,
                source_path=self._source_config,
                profile_name=model_profile,
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            raise ConfigurationError(
                f"GPT-SoVITS model profile '{model_profile}' could not be validated."
            ) from exc
        supported = _PROMPT_LANGUAGES_BY_MODEL_VERSION[version]
        if language not in supported:
            rendered = ", ".join(sorted(supported))
            raise ConfigurationError(
                f"Configured {label} language '{language}' is unsupported by "
                f"model profile '{model_profile}' ({rendered})."
            )
        return language

    async def _validate_resolved_voice_profile(
        self,
        profile: ResolvedVoiceProfile,
    ) -> _ValidatedVoiceProfile:
        actual = set(profile.emotion_refs)
        expected = set(EMOTION_REFERENCE_KEYS)
        if actual != expected:
            raise ConfigurationError(
                "Configured voice profile must provide exactly seven emotion references."
            )
        if not profile.model_profile.strip():
            raise ConfigurationError("Configured voice profile model profile is blank.")
        gpt_weights, sovits_weights = self._validate_weight_pair(
            profile.gpt_weights_path,
            profile.sovits_weights_path,
        )
        default_emotion = normalize_speech_emotion(profile.default_emotion)
        if default_emotion is None:
            raise ConfigurationError("Configured voice profile default emotion is invalid.")
        prompt_language = await self._validated_prompt_language(
            profile.reference_language or self._prompt_language,
            model_profile=profile.model_profile,
            label=f"{profile.speaker_id} reference",
        )
        references: dict[SpeechEmotion, tuple[Path, str]] = {}
        for emotion in EMOTION_REFERENCE_KEYS:
            reference = profile.emotion_refs[emotion]
            references[emotion] = await self._validate_reference(
                reference,
                label=f"{profile.speaker_id} {emotion.value} reference",
            )
        return _ValidatedVoiceProfile(
            runtime=_VoiceRuntime(profile.model_profile, gpt_weights, sovits_weights),
            default_emotion=default_emotion,
            emotion_refs=references,
            prompt_language=prompt_language,
        )

    async def _resolve_segment_voice_plans(
        self,
        script: ScriptDocument,
    ) -> list[_SegmentVoicePlan]:
        profiles: dict[str, _ValidatedVoiceProfile | None] = {}
        legacy_reference: tuple[Path, str] | None = None
        legacy_prompt_language: str | None = None
        plans: list[_SegmentVoicePlan] = []
        for segment in script.segments:
            if segment.speaker_id not in profiles:
                profile: ResolvedVoiceProfile | None = None
                if self._voice_resolver is not None:
                    try:
                        profile = await self._voice_resolver.resolve_voice(segment.speaker_id)
                    except (ConfigurationError, TTSGenerationError):
                        raise
                    except Exception as exc:
                        raise TTSGenerationError(
                            "Voice profile resolution failed for speaker_id "
                            f"'{segment.speaker_id}'."
                        ) from exc
                profiles[segment.speaker_id] = (
                    None
                    if profile is None
                    else await self._validate_resolved_voice_profile(profile)
                )
            profile_assets = profiles[segment.speaker_id]
            emotion = normalize_speech_emotion(segment.emotion)
            if emotion is None:
                raise TTSGenerationError(
                    f"segment {segment.sequence} has an unsupported emotion label."
                )
            if profile_assets is None:
                if segment.speaker_id != self._default_speaker_id:
                    raise TTSGenerationError(
                        f"speaker_id '{segment.speaker_id}' has no enabled synthesis-capable "
                        "voice profile."
                    )
                if legacy_reference is None:
                    legacy_reference = await self._load_legacy_reference()
                    legacy_prompt_language = await self._validated_prompt_language(
                        self._prompt_language,
                        model_profile=self._model_profile,
                        label="legacy reference",
                    )
                reference_audio_path, reference_text = legacy_reference
                if legacy_prompt_language is None:
                    raise TTSGenerationError("Legacy reference language was not resolved.")
                runtime = _VoiceRuntime(
                    self._model_profile,
                    self._gpt_weights,
                    self._sovits_weights,
                )
                prompt_language = legacy_prompt_language
            else:
                selected_emotion = emotion
                if selected_emotion not in profile_assets.emotion_refs:
                    selected_emotion = profile_assets.default_emotion
                reference_audio_path, reference_text = profile_assets.emotion_refs[selected_emotion]
                emotion = selected_emotion
                runtime = profile_assets.runtime
                prompt_language = profile_assets.prompt_language
            plans.append(
                _SegmentVoicePlan(
                    segment=segment,
                    runtime=runtime,
                    emotion=emotion,
                    reference_audio_path=reference_audio_path,
                    reference_text=reference_text,
                    prompt_language=prompt_language,
                )
            )
        return plans

    async def _synthesize_exclusive(
        self,
        story_id: UUID,
        script: ScriptDocument,
        plans: list[_SegmentVoicePlan],
    ) -> AudioBundle:
        story_dir = self._output_dir / str(story_id) / f"r{script.revision}" / f"attempt-{uuid4()}"
        await asyncio.to_thread(story_dir.mkdir, parents=True, exist_ok=True)
        temp_root = self._output_dir / ".runtime"
        await asyncio.to_thread(temp_root.mkdir, parents=True, exist_ok=True)
        temporary = tempfile.mkdtemp(prefix=f"{story_id}-", dir=temp_root)
        temp_dir = Path(temporary)
        published = False
        try:
            clips, provenance, representative_runtime = await self._generate_clips(
                plans=plans,
                story_dir=story_dir,
                temp_dir=temp_dir,
            )
            representative_plan = plans[0]
            bundle = AudioBundle(
                revision=script.revision,
                provider="gpt-sovits-api-v2",
                # Existing consumers read these bundle-level fields as one
                # voice. They deterministically describe the first clip;
                # segment_provenance below carries the complete multi-role truth.
                model_identity=representative_runtime.prepared.model_identity,
                synthesis=SynthesisMetadata(
                    seed=self._seed,
                    reference_audio_sha256=provenance[0].reference_audio_sha256,
                    runtime_config_sha256=representative_runtime.runtime_config_sha256,
                    gpt_weights_sha256=representative_runtime.gpt_weights_sha256,
                    sovits_weights_sha256=representative_runtime.sovits_weights_sha256,
                    prompt_language=representative_plan.prompt_language,
                    text_language=self._text_language,
                    segment_provenance=provenance,
                ),
                clips=clips,
            )
            published = True
            return bundle
        except (ConfigurationError, TTSGenerationError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise TTSGenerationError("GPT-SoVITS synthesis failed.", story_id) from exc
        finally:
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)
            if not published:
                await asyncio.to_thread(shutil.rmtree, story_dir, True)

    async def _start_runtime(
        self,
        runtime: _VoiceRuntime,
        runtime_config: Path,
    ) -> _ActiveRuntime:
        prepared = await asyncio.to_thread(
            _prepare_runtime_config,
            source_path=self._source_config,
            destination_path=runtime_config,
            root=self._root,
            profile_name=runtime.model_profile,
            gpt_weights=runtime.gpt_weights_path,
            sovits_weights=runtime.sovits_weights_path,
            device=self._device,
            use_half_precision=self._use_half_precision,
        )
        # Snapshot both large files immediately before startup, then re-hash
        # once the vendor server is ready. This closes the meaningful window
        # where an operator could replace a weight pair while it is loading and
        # leave provenance describing the wrong model.
        gpt_snapshot = await self._snapshot_file(
            prepared.gpt_weights_path,
            label="GPT voice weights",
        )
        sovits_snapshot = await self._snapshot_file(
            prepared.sovits_weights_path,
            label="SoVITS voice weights",
        )
        server = await self._start_server(runtime_config)
        try:
            await self._assert_snapshot_unchanged(
                gpt_snapshot,
                label="GPT voice weights",
                verify_content=True,
            )
            await self._assert_snapshot_unchanged(
                sovits_snapshot,
                label="SoVITS voice weights",
                verify_content=True,
            )
        except BaseException:
            await asyncio.shield(self._stop_server(server))
            raise
        return _ActiveRuntime(
            server=server,
            prepared=prepared,
            runtime_config_sha256=await asyncio.to_thread(_sha256_file, runtime_config),
            gpt_weights_sha256=gpt_snapshot.sha256,
            sovits_weights_sha256=sovits_snapshot.sha256,
            gpt_weights_snapshot=gpt_snapshot,
            sovits_weights_snapshot=sovits_snapshot,
        )

    @staticmethod
    def _file_stat_signature(path: Path) -> tuple[Path, int, int]:
        resolved = path.expanduser().resolve(strict=True)
        status = resolved.stat()
        if not resolved.is_file():
            raise ValueError("path is not a regular file")
        return resolved, int(status.st_size), int(status.st_mtime_ns)

    async def _snapshot_file(
        self,
        path: Path,
        *,
        label: str,
        force_refresh: bool = False,
    ) -> _FileSnapshot:
        """Hash a file and prove its size/mtime did not move during the hash."""

        try:
            resolved, size_bytes, modified_ns = await asyncio.to_thread(
                self._file_stat_signature,
                path,
            )
        except (OSError, ValueError) as exc:
            raise ConfigurationError(f"Configured {label} could not be statted.") from exc
        cache_key = (resolved, size_bytes, modified_ns)
        digest = None if force_refresh else self._file_hash_cache.get(cache_key)
        if digest is None:
            try:
                digest = await asyncio.to_thread(_sha256_file, resolved)
            except OSError as exc:
                raise ConfigurationError(f"Configured {label} could not be hashed.") from exc
            self._file_hash_cache[cache_key] = digest
        try:
            after_path, after_size, after_modified_ns = await asyncio.to_thread(
                self._file_stat_signature,
                resolved,
            )
        except (OSError, ValueError) as exc:
            raise ConfigurationError(f"Configured {label} changed while it was hashed.") from exc
        if (after_path, after_size, after_modified_ns) != cache_key:
            raise ConfigurationError(f"Configured {label} changed while it was hashed.")
        return _FileSnapshot(
            path=resolved,
            size_bytes=size_bytes,
            modified_ns=modified_ns,
            sha256=digest,
        )

    async def _assert_snapshot_unchanged(
        self,
        snapshot: _FileSnapshot,
        *,
        label: str,
        verify_content: bool = False,
    ) -> None:
        """Fail closed rather than attach stale provenance to generated audio."""

        current = await self._snapshot_file(
            snapshot.path,
            label=label,
            force_refresh=verify_content,
        )
        if current != snapshot:
            raise ConfigurationError(
                f"Configured {label} changed during active GPT-SoVITS synthesis."
            )

    async def _cached_file_hash(self, path: Path) -> str:
        """Compatibility helper backed by a metadata-aware cache key."""

        return (await self._snapshot_file(path, label="voice asset")).sha256

    async def _start_server(self, runtime_config: Path) -> _ServerProcess:
        port = await asyncio.to_thread(_choose_loopback_port)
        env = sanitized_subprocess_env()
        runtime_dir = str((self._root / "runtime").resolve())
        env["PATH"] = runtime_dir + os.pathsep + env.get("PATH", "")
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000 | 0x00000200
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._python.resolve()),
                "-I",
                str((self._root / "api_v2.py").resolve()),
                "-a",
                "127.0.0.1",
                "-p",
                str(port),
                "-c",
                str(runtime_config),
                cwd=str(self._root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise ConfigurationError("GPT-SoVITS runtime could not be started.") from exc
        job_handle = await asyncio.to_thread(attach_kill_on_close_job, process.pid)
        tail: deque[str] = deque(maxlen=100)
        handle = _ServerProcess(
            process=process,
            stdout_task=asyncio.create_task(_drain_stream(process.stdout, tail, "stdout")),
            stderr_task=asyncio.create_task(_drain_stream(process.stderr, tail, "stderr")),
            log_tail=tail,
            port=port,
            job_handle=job_handle,
        )
        self._active[process.pid] = handle
        try:
            deadline = asyncio.get_running_loop().time() + self._startup_timeout
            async with httpx.AsyncClient(
                trust_env=False,
                timeout=self._probe_timeout,
            ) as client:
                while asyncio.get_running_loop().time() < deadline:
                    if process.returncode is not None:
                        raise TTSGenerationError("GPT-SoVITS exited during startup.")
                    try:
                        response = await client.get(f"http://127.0.0.1:{port}/openapi.json")
                        if response.status_code == 200:
                            return handle
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(self._startup_poll_interval)
            raise TTSGenerationError("GPT-SoVITS did not become ready before the startup deadline.")
        except BaseException:
            await asyncio.shield(self._stop_server(handle))
            raise

    async def _generate_clips(
        self,
        *,
        plans: list[_SegmentVoicePlan],
        story_dir: Path,
        temp_dir: Path,
    ) -> tuple[list[AudioClip], list[SegmentSynthesisProvenance], _ActiveRuntime]:
        clips: list[AudioClip] = []
        provenance: list[SegmentSynthesisProvenance] = []
        active_runtime_key: _VoiceRuntime | None = None
        active_runtime: _ActiveRuntime | None = None
        representative_runtime: _ActiveRuntime | None = None
        activation_index = 0
        timeout = httpx.Timeout(self._request_timeout)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
                # Keep clip emission in authored sequence. To protect the 24GB
                # GPU, a weight switch always drains and kills the prior local
                # process before the next isolated runtime starts.
                for plan in plans:
                    if plan.runtime != active_runtime_key:
                        if active_runtime is not None:
                            await asyncio.shield(self._stop_server(active_runtime.server))
                        active_runtime = await self._start_runtime(
                            plan.runtime,
                            temp_dir / f"tts_infer-{activation_index}.yaml",
                        )
                        activation_index += 1
                        active_runtime_key = plan.runtime
                        if representative_runtime is None:
                            representative_runtime = active_runtime
                    if active_runtime is None:
                        raise TTSGenerationError("GPT-SoVITS runtime did not start.")
                    await self._assert_snapshot_unchanged(
                        active_runtime.gpt_weights_snapshot,
                        label="GPT voice weights",
                    )
                    await self._assert_snapshot_unchanged(
                        active_runtime.sovits_weights_snapshot,
                        label="SoVITS voice weights",
                    )
                    reference_snapshot = await self._snapshot_file(
                        plan.reference_audio_path,
                        label=f"{plan.segment.speaker_id} reference audio",
                    )
                    clip = await self._generate_clip(
                        client=client,
                        server=active_runtime.server,
                        segment=plan.segment,
                        story_dir=story_dir,
                        reference_audio_path=plan.reference_audio_path,
                        reference_text=plan.reference_text,
                        prompt_language=plan.prompt_language,
                    )
                    await self._assert_snapshot_unchanged(
                        reference_snapshot,
                        label=f"{plan.segment.speaker_id} reference audio",
                        verify_content=True,
                    )
                    await self._assert_snapshot_unchanged(
                        active_runtime.gpt_weights_snapshot,
                        label="GPT voice weights",
                    )
                    await self._assert_snapshot_unchanged(
                        active_runtime.sovits_weights_snapshot,
                        label="SoVITS voice weights",
                    )
                    clips.append(clip)
                    provenance.append(
                        SegmentSynthesisProvenance(
                            segment_id=plan.segment.segment_id,
                            speaker_id=plan.segment.speaker_id,
                            emotion=plan.emotion,
                            reference_audio_sha256=reference_snapshot.sha256,
                            reference_text_sha256=hashlib.sha256(
                                plan.reference_text.encode("utf-8")
                            ).hexdigest(),
                            gpt_weights_sha256=active_runtime.gpt_weights_sha256,
                            sovits_weights_sha256=active_runtime.sovits_weights_sha256,
                            model_identity=active_runtime.prepared.model_identity,
                            prompt_language=plan.prompt_language,
                        )
                    )
        finally:
            if active_runtime is not None:
                await asyncio.shield(self._stop_server(active_runtime.server))
        if representative_runtime is None:
            raise TTSGenerationError("GPT-SoVITS received no script segments.")
        return clips, provenance, representative_runtime

    async def _generate_clip(
        self,
        *,
        client: httpx.AsyncClient,
        server: _ServerProcess,
        segment: ScriptSegment,
        story_dir: Path,
        reference_audio_path: Path,
        reference_text: str,
        prompt_language: str,
    ) -> AudioClip:
        request = _TTSRequest(
            text=segment.spoken_text,
            text_lang=self._text_language,
            ref_audio_path=str(reference_audio_path),
            prompt_text=reference_text,
            prompt_lang=prompt_language,
            speed_factor=segment.speed,
            seed=self._seed,
            top_k=self._top_k,
            top_p=self._top_p,
            temperature=self._temperature,
            text_split_method=self._text_split_method,
            batch_size=self._batch_size,
            batch_threshold=self._batch_threshold,
            fragment_interval=self._fragment_interval,
            repetition_penalty=self._repetition_penalty,
            parallel_infer=self._parallel_infer,
        )
        final_path = story_dir / f"{segment.sequence:03d}-{segment.segment_id}.wav"
        partial_path = final_path.with_suffix(".wav.part")
        digest = hashlib.sha256()
        header = bytearray()
        size = 0
        try:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{server.port}/tts",
                json=request.model_dump(),
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    vendor_message = ""
                    try:
                        payload = json.loads(body[:4_096].decode("utf-8", errors="strict"))
                        candidate = payload.get("message") if isinstance(payload, dict) else None
                        if isinstance(candidate, str):
                            vendor_message = self._sanitize_vendor_message(candidate)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                    detail = f" Vendor message: {vendor_message}." if vendor_message else ""
                    raise TTSGenerationError(
                        f"GPT-SoVITS rejected segment {segment.sequence} with "
                        f"HTTP {response.status_code}.{detail}"
                    )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._max_audio_bytes:
                    raise TTSGenerationError("GPT-SoVITS audio exceeded the configured size limit.")
                async with await anyio.open_file(partial_path, "wb") as output:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_audio_bytes:
                            raise TTSGenerationError(
                                "GPT-SoVITS audio exceeded the configured size limit."
                            )
                        if len(header) < 12:
                            header.extend(chunk[: 12 - len(header)])
                        digest.update(chunk)
                        await output.write(chunk)
            if not header.startswith(b"RIFF") or header[8:12] != b"WAVE":
                raise TTSGenerationError("GPT-SoVITS returned invalid WAV data.")
            info = await asyncio.to_thread(_inspect_wav, partial_path)
            await asyncio.to_thread(partial_path.replace, final_path)
        except httpx.TimeoutException as exc:
            server.force_shutdown = True
            await asyncio.shield(
                terminate_process_tree(
                    server.process,
                    grace_seconds=self._process_kill_grace,
                )
            )
            raise TTSGenerationError("GPT-SoVITS request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TTSGenerationError("GPT-SoVITS request failed.") from exc
        except (OSError, wave.Error, ValueError) as exc:
            raise TTSGenerationError("Synthesized WAV could not be validated or stored.") from exc
        finally:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(partial_path.unlink)
        relative_path = final_path.relative_to(self._output_dir).as_posix()
        return AudioClip(
            segment_id=segment.segment_id,
            path=relative_path,
            format=AudioFormat.WAV,
            duration_ms=info.duration_ms,
            sample_rate_hz=info.sample_rate_hz,
            channels=info.channels,
            sha256=digest.hexdigest(),
        )

    @staticmethod
    def _sanitize_vendor_message(message: str) -> str:
        sanitized = " ".join(message.split())
        sanitized = re.sub(
            r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s,;\"']+",
            "<local-path>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)(?<![A-Za-z0-9:])/(?:home|Users|tmp|var/tmp|mnt|opt|private)/"
            r"[^\s,;\"']+",
            "<local-path>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)\b(?:bearer\s+|sk-)[A-Za-z0-9._-]{8,}\b",
            "<secret>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)\b(?:api[_-]?key|token|secret)=[^\s,;]+",
            "<secret>",
            sanitized,
        )
        return sanitized[:200]

    async def _stop_server(self, server: _ServerProcess) -> None:
        async with server.stop_lock:
            if server.process.pid not in self._active:
                return
            try:
                if server.process.returncode is None and not server.force_shutdown:
                    try:
                        async with httpx.AsyncClient(
                            trust_env=False,
                            timeout=self._probe_timeout,
                        ) as client:
                            await client.get(
                                f"http://127.0.0.1:{server.port}/control",
                                params={"command": "exit"},
                            )
                    except httpx.HTTPError:
                        pass
                if server.process.returncode is None:
                    try:
                        await asyncio.wait_for(
                            server.process.wait(),
                            timeout=(
                                self._force_shutdown_wait
                                if server.force_shutdown
                                else self._shutdown_timeout
                            ),
                        )
                    except TimeoutError:
                        await terminate_process_tree(
                            server.process,
                            grace_seconds=min(
                                self._process_kill_grace,
                                self._shutdown_timeout,
                            ),
                        )
            finally:
                await asyncio.to_thread(close_kill_on_close_job, server.job_handle)
                self._active.pop(server.process.pid, None)
            drains = asyncio.gather(
                server.stdout_task,
                server.stderr_task,
                return_exceptions=True,
            )
            try:
                await asyncio.wait_for(drains, timeout=self._drain_timeout)
            except TimeoutError:
                server.stdout_task.cancel()
                server.stderr_task.cancel()
                await asyncio.gather(
                    server.stdout_task,
                    server.stderr_task,
                    return_exceptions=True,
                )

    async def aclose(self) -> None:
        await asyncio.gather(
            *(self._stop_server(server) for server in tuple(self._active.values())),
            return_exceptions=True,
        )


class UnavailableSpeechSynthesizer:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def healthcheck(self) -> None:
        raise ConfigurationError(self._reason)

    async def synthesize(self, story_id: UUID, script: ScriptDocument) -> AudioBundle:
        del script
        raise TTSGenerationError(self._reason, story_id)

    async def aclose(self) -> None:
        return None
