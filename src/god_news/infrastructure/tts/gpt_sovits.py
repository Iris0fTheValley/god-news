from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shutil
import socket
import tempfile
import wave
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import anyio
import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from god_news.domain.enums import AudioFormat
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    ScriptDocument,
    ScriptSegment,
    SynthesisMetadata,
)
from god_news.errors import ConfigurationError, TTSGenerationError
from god_news.infrastructure.processes import (
    attach_kill_on_close_job,
    close_kill_on_close_job,
    sanitized_subprocess_env,
    terminate_process_tree,
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
        self._gpt_weights = gpt_weights
        self._sovits_weights = sovits_weights
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
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[int, _ServerProcess] = {}
        self._file_hash_cache: dict[Path, str] = {}

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
        reference_text = (
            await asyncio.to_thread(self._reference_text_file.read_text, encoding="utf-8")
        ).strip()
        if not reference_text:
            raise ConfigurationError("GPT-SoVITS reference transcript is empty.")
        try:
            info = await asyncio.to_thread(_inspect_wav, self._reference_audio)
        except (OSError, ValueError, wave.Error) as exc:
            raise ConfigurationError("GPT-SoVITS reference audio is not a valid WAV.") from exc
        if not 3_000 <= info.duration_ms <= 10_000:
            raise ConfigurationError("GPT-SoVITS reference audio must be 3 to 10 seconds long.")

    async def synthesize(self, story_id: UUID, script: ScriptDocument) -> AudioBundle:
        self._validate_capabilities(script)
        self._validate_paths()
        async with self._semaphore:
            return await self._synthesize_exclusive(story_id, script)

    def _validate_paths(self) -> None:
        required = (
            self._root,
            self._python,
            self._root / "api_v2.py",
            self._source_config,
            self._reference_audio,
            self._reference_text_file,
        )
        if any(not path.exists() for path in required):
            raise ConfigurationError("GPT-SoVITS paths are incomplete or do not exist.")
        for path in (self._source_config, self._reference_audio, self._reference_text_file):
            if not _within(path, self._root):
                raise ConfigurationError(
                    "GPT-SoVITS voice resources must stay inside its root directory."
                )
        if self._gpt_weights is not None and not self._gpt_weights.exists():
            raise ConfigurationError("Configured GPT voice weights do not exist.")
        if self._sovits_weights is not None and not self._sovits_weights.exists():
            raise ConfigurationError("Configured SoVITS voice weights do not exist.")

    def _validate_capabilities(self, script: ScriptDocument) -> None:
        for segment in script.segments:
            if segment.speaker_id != self._default_speaker_id:
                raise TTSGenerationError(
                    f"speaker_id '{segment.speaker_id}' has no configured GPT-SoVITS voice profile."
                )
            if segment.emotion != "neutral":
                raise TTSGenerationError(
                    "GPT-SoVITS has no native emotion field; configure an emotion-specific "
                    "voice profile."
                )
            if segment.pitch != 0:
                raise TTSGenerationError("GPT-SoVITS does not support pitch control.")

    async def _synthesize_exclusive(self, story_id: UUID, script: ScriptDocument) -> AudioBundle:
        story_dir = self._output_dir / str(story_id) / f"r{script.revision}" / f"attempt-{uuid4()}"
        await asyncio.to_thread(story_dir.mkdir, parents=True, exist_ok=True)
        temp_root = self._output_dir / ".runtime"
        await asyncio.to_thread(temp_root.mkdir, parents=True, exist_ok=True)
        temporary = tempfile.mkdtemp(prefix=f"{story_id}-", dir=temp_root)
        temp_dir = Path(temporary)
        runtime_config = temp_dir / "tts_infer.yaml"
        server: _ServerProcess | None = None
        published = False
        try:
            prepared = await asyncio.to_thread(
                _prepare_runtime_config,
                source_path=self._source_config,
                destination_path=runtime_config,
                root=self._root,
                profile_name=self._model_profile,
                gpt_weights=self._gpt_weights,
                sovits_weights=self._sovits_weights,
                device=self._device,
                use_half_precision=self._use_half_precision,
            )
            reference_text = (
                await asyncio.to_thread(self._reference_text_file.read_text, encoding="utf-8")
            ).strip()
            if not reference_text:
                raise ConfigurationError("GPT-SoVITS reference transcript is empty.")
            reference_hash = await asyncio.to_thread(_sha256_file, self._reference_audio)
            server = await self._start_server(runtime_config)
            runtime_hash = await asyncio.to_thread(_sha256_file, runtime_config)
            gpt_hash = await self._cached_file_hash(prepared.gpt_weights_path)
            sovits_hash = await self._cached_file_hash(prepared.sovits_weights_path)
            clips = await self._generate_clips(
                server=server,
                script=script,
                story_dir=story_dir,
                reference_text=reference_text,
            )
            bundle = AudioBundle(
                revision=script.revision,
                provider="gpt-sovits-api-v2",
                model_identity=prepared.model_identity,
                synthesis=SynthesisMetadata(
                    seed=self._seed,
                    reference_audio_sha256=reference_hash,
                    runtime_config_sha256=runtime_hash,
                    gpt_weights_sha256=gpt_hash,
                    sovits_weights_sha256=sovits_hash,
                    prompt_language=self._prompt_language,
                    text_language=self._text_language,
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
            if server is not None:
                await asyncio.shield(self._stop_server(server))
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)
            if not published:
                await asyncio.to_thread(shutil.rmtree, story_dir, True)

    async def _cached_file_hash(self, path: Path) -> str:
        cached = self._file_hash_cache.get(path)
        if cached is not None:
            return cached
        digest = await asyncio.to_thread(_sha256_file, path)
        self._file_hash_cache[path] = digest
        return digest

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
        server: _ServerProcess,
        script: ScriptDocument,
        story_dir: Path,
        reference_text: str,
    ) -> list[AudioClip]:
        clips: list[AudioClip] = []
        timeout = httpx.Timeout(self._request_timeout)
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
            for segment in script.segments:
                clip = await self._generate_clip(
                    client=client,
                    server=server,
                    segment=segment,
                    story_dir=story_dir,
                    reference_text=reference_text,
                )
                clips.append(clip)
        return clips

    async def _generate_clip(
        self,
        *,
        client: httpx.AsyncClient,
        server: _ServerProcess,
        segment: ScriptSegment,
        story_dir: Path,
        reference_text: str,
    ) -> AudioClip:
        request = _TTSRequest(
            text=segment.text,
            text_lang=self._text_language,
            ref_audio_path=str(self._reference_audio.resolve()),
            prompt_text=reference_text,
            prompt_lang=self._prompt_language,
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
                    raise TTSGenerationError(
                        f"GPT-SoVITS rejected segment {segment.sequence} with "
                        f"HTTP {response.status_code}."
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
