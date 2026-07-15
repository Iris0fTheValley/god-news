from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from god_news.domain.source_transcription import (
    ASRTranscript,
    SourceMediaTranscriber,
    SourceMediaTranscriberError,
)
from god_news.infrastructure.processes import run_json_worker


class FasterWhisperWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_path: str
    model: str
    device: str
    compute_type: str
    download_root: str
    local_files_only: bool
    cpu_threads: int = Field(ge=1, le=64)
    beam_size: int = Field(ge=1, le=20)
    vad_filter: bool
    language_hint: str | None = None


class FasterWhisperWorkerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    transcript: ASRTranscript | None = None
    error_code: str | None = None


class FasterWhisperSourceMediaTranscriber(SourceMediaTranscriber):
    """One-shot local ASR worker; model memory dies with each supervised child."""

    def __init__(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        download_root: Path,
        local_files_only: bool,
        timeout_seconds: float,
        max_output_bytes: int,
        cpu_threads: int,
        beam_size: int,
        vad_filter: bool,
        worker_module: str = "god_news.workers.faster_whisper_transcribe",
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._model = model
        self._device = device
        self._compute_type = compute_type
        self._download_root = download_root.expanduser().resolve(strict=False)
        self._local_files_only = local_files_only
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._cpu_threads = cpu_threads
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._worker_module = worker_module
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    @property
    def model_identity(self) -> str:
        return (
            f"faster-whisper:1.2.1:{self._model}:"
            f"{self._device}:{self._compute_type}"
        )

    async def transcribe(self, path: Path, *, language_hint: str | None) -> ASRTranscript:
        try:
            resolved = await asyncio.to_thread(_resolve_regular_file, path)
        except (OSError, ValueError) as exc:
            raise SourceMediaTranscriberError(
                "media_missing",
                "Source media is not a regular file.",
                retryable=False,
            ) from exc
        await asyncio.to_thread(self._download_root.mkdir, parents=True, exist_ok=True)
        request = FasterWhisperWorkerRequest(
            media_path=str(resolved),
            model=self._model,
            device=self._device,
            compute_type=self._compute_type,
            download_root=str(self._download_root),
            local_files_only=self._local_files_only,
            cpu_threads=self._cpu_threads,
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            language_hint=language_hint,
        )
        try:
            async with self._semaphore:
                response = await run_json_worker(
                    command=(sys.executable, "-m", self._worker_module),
                    request=request,
                    response_type=FasterWhisperWorkerResponse,
                    timeout_seconds=self._timeout_seconds,
                    max_stdout_bytes=self._max_output_bytes,
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise SourceMediaTranscriberError(
                "asr_timeout",
                "Local ASR exceeded its configured deadline.",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise SourceMediaTranscriberError(
                "asr_worker_failed",
                "Local ASR worker failed to execute.",
                retryable=True,
            ) from exc
        if not response.ok or response.transcript is None:
            code = response.error_code or "asr_failed"
            retryable = code not in {"no_speech_detected", "media_missing", "invalid_request"}
            raise SourceMediaTranscriberError(
                code,
                "Local ASR did not produce a usable transcript.",
                retryable=retryable,
            )
        return response.transcript


def _resolve_regular_file(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("media path is not a regular file")
    return resolved
