from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from god_news.domain.models import AudioBundle, AudioClip, ScriptDocument, ScriptSegment
from god_news.domain.video import HostVisualReservations, RenderedHostVideo
from god_news.infrastructure.processes import (
    attach_kill_on_close_job,
    close_kill_on_close_job,
    sanitized_subprocess_env,
    terminate_process_tree,
)
from god_news.infrastructure.source_media_probe import FFprobeSourceVideoInspector
from god_news.operations.models import RoleProfile
from god_news.video_errors import VideoNarrationSynthesisError


class RoleVisualProfileReader(Protocol):
    async def get_enabled_by_speaker_id(self, speaker_id: str) -> RoleProfile | None: ...


class LocalLive2DHostRenderer:
    """Pre-render DSakiko-compatible Cubism 2 roles into transparent WebM.

    Each narration segment runs in its own bounded subprocess. This isolates the
    native Live2D/OpenGL runtime from FastAPI and turns the renderer-facing
    contract into an immutable ordinary media file rather than SDK state.
    """

    def __init__(
        self,
        *,
        profiles: RoleVisualProfileReader,
        python_executable: str | Path,
        worker_script: Path,
        inspector: FFprobeSourceVideoInspector,
        output_root: Path,
        trusted_asset_roots: Sequence[Path],
        timeout_seconds: float,
        max_parallel_segments: int,
        width: int,
        height: int,
        fps: int,
    ) -> None:
        self._profiles = profiles
        self._python = self._resolve_executable(python_executable, "Live2D Python")
        self._worker = worker_script.expanduser().resolve(strict=True)
        if not self._worker.is_file():
            raise ValueError("Live2D worker script is not a file")
        self._inspector = inspector
        self._output_root = output_root.expanduser().resolve(strict=False)
        if self._output_root.parent == self._output_root:
            raise ValueError("Live2D output root cannot be a filesystem root")
        roots = tuple(root.expanduser().resolve(strict=True) for root in trusted_asset_roots)
        if not roots or any(not root.is_dir() or root.parent == root for root in roots):
            raise ValueError("Live2D trusted asset roots must be non-root directories")
        if len(roots) != len(set(roots)):
            raise ValueError("Live2D trusted asset roots must be unique")
        self._trusted_roots = roots
        self._timeout_seconds = timeout_seconds
        self._slots = asyncio.Semaphore(max_parallel_segments)
        self._width = width
        self._height = height
        self._fps = fps

    @property
    def name(self) -> str:
        return "live2d-prerender"

    async def prepare(
        self,
        *,
        batch_id: UUID,
        script: ScriptDocument,
        audio: AudioBundle,
    ) -> HostVisualReservations:
        clips = {clip.segment_id: clip for clip in audio.clips}
        if set(clips) != {segment.segment_id for segment in script.segments}:
            raise VideoNarrationSynthesisError(
                "Live2D host rendering requires audio for every approved narration segment.",
                retryable=False,
            )
        tasks = [
            asyncio.create_task(
                self._render_segment(batch_id, segment, clips[segment.segment_id])
            )
            for segment in script.segments
        ]
        try:
            assets = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(self._cleanup_batch_output, batch_id)
            raise
        return HostVisualReservations(renderer="live2d_prerender", host_videos=list(assets))

    def _cleanup_batch_output(self, batch_id: UUID) -> None:
        batch_root = (self._output_root / str(batch_id)).resolve(strict=False)
        if batch_root.parent == self._output_root and batch_root.is_dir():
            shutil.rmtree(batch_root, ignore_errors=True)

    async def _render_segment(
        self,
        batch_id: UUID,
        segment: ScriptSegment,
        clip: AudioClip,
    ) -> RenderedHostVideo:
        async with self._slots:
            profile = await self._profiles.get_enabled_by_speaker_id(segment.speaker_id)
            if profile is None or profile.visual_assets.live2d_asset_ref is None:
                raise VideoNarrationSynthesisError(
                    f"Speaker {segment.speaker_id!r} has no enabled Live2D role asset.",
                    retryable=False,
                )
            model_path = await asyncio.to_thread(
                self._resolve_model_path,
                profile.visual_assets.live2d_asset_ref,
            )
            model_sha256 = await asyncio.to_thread(self._model_tree_sha256, model_path)
            audio_path = await asyncio.to_thread(
                lambda: Path(clip.path).expanduser().resolve(strict=True)
            )
            batch_root = self._output_root / str(batch_id)
            resolved_batch_root = batch_root.resolve(strict=False)
            if resolved_batch_root.parent != self._output_root:
                raise VideoNarrationSynthesisError(
                    "Live2D batch output escaped the configured media root.",
                    retryable=False,
                )
            await asyncio.to_thread(resolved_batch_root.mkdir, parents=True, exist_ok=True)
            output = resolved_batch_root / f"{segment.sequence:03d}-{segment.segment_id}.webm"
            temporary = output.with_name(f"{output.stem}.partial.webm")
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            try:
                await self._run_worker(
                    model_path=model_path,
                    audio_path=audio_path,
                    output_path=temporary,
                    duration_ms=clip.duration_ms,
                    emotion=segment.emotion.value,
                )
                probe = await self._inspector.inspect(temporary)
                frame_tolerance_ms = max(100, round(2_000 / self._fps))
                if (
                    probe.video_codec != "vp9"
                    or probe.width != self._width
                    or probe.height != self._height
                    or abs(probe.fps - self._fps) > 0.01
                    or abs(probe.duration_ms - clip.duration_ms) > frame_tolerance_ms
                ):
                    raise VideoNarrationSynthesisError(
                        "Live2D worker returned media outside its declared capability contract.",
                        retryable=False,
                    )
                size_bytes, digest = await asyncio.to_thread(self._file_evidence, temporary)
                await asyncio.to_thread(os.replace, temporary, output)
            except Exception:
                await asyncio.to_thread(temporary.unlink, missing_ok=True)
                raise
            return RenderedHostVideo(
                segment_id=segment.segment_id,
                speaker_id=segment.speaker_id,
                role_profile_id=profile.profile_id,
                role_profile_version=profile.version,
                model_sha256=model_sha256,
                audio_sha256=clip.sha256,
                local_path=str(output),
                sha256=digest,
                size_bytes=size_bytes,
                duration_ms=clip.duration_ms,
                width=self._width,
                height=self._height,
                fps=self._fps,
                video_codec="vp9",
            )

    async def _run_worker(
        self,
        *,
        model_path: Path,
        audio_path: Path,
        output_path: Path,
        duration_ms: int,
        emotion: str,
    ) -> None:
        command = [
            self._python,
            str(self._worker),
            "--model",
            str(model_path),
            "--audio",
            str(audio_path),
            "--output",
            str(output_path),
            "--emotion",
            emotion,
            "--duration-ms",
            str(duration_ms),
            "--width",
            str(self._width),
            "--height",
            str(self._height),
            "--fps",
            str(self._fps),
        ]
        creationflags = 0x08000000 | 0x00000200 if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._worker.parent.parent),
            env=sanitized_subprocess_env(),
            creationflags=creationflags,
        )
        job = await asyncio.to_thread(attach_kill_on_close_job, process.pid)
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout_seconds,
                )
            except (TimeoutError, asyncio.CancelledError):
                await asyncio.shield(terminate_process_tree(process))
                raise
        finally:
            await asyncio.to_thread(close_kill_on_close_job, job)
        if len(stdout) > 16_384 or len(stderr) > 65_536:
            raise VideoNarrationSynthesisError(
                "Live2D worker exceeded its bounded diagnostic output.",
                retryable=False,
            )
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-4_000:]
            raise VideoNarrationSynthesisError(
                f"Live2D worker exited with code {process.returncode}: {detail}"
            )
        try:
            diagnostic = json.loads(stdout.decode("utf-8", errors="strict").strip())
            expected_frames = max(1, round(duration_ms * self._fps / 1_000))
            if (
                diagnostic.get("frames") != expected_frames
                or diagnostic.get("rendered_frames") != expected_frames
                or diagnostic.get("fps") != self._fps
            ):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, ValueError) as exc:
            raise VideoNarrationSynthesisError(
                "Live2D worker returned an invalid frame-count diagnostic.",
                retryable=False,
            ) from exc

    def _resolve_model_path(self, reference: str) -> Path:
        candidate = Path(reference).expanduser()
        matches: list[Path] = []
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=True)
            if any(resolved.is_relative_to(root) for root in self._trusted_roots):
                matches.append(resolved)
        else:
            for root in self._trusted_roots:
                resolved = (root / candidate).resolve(strict=False)
                if resolved.is_relative_to(root) and resolved.is_file():
                    matches.append(resolved.resolve(strict=True))
        matches = list(dict.fromkeys(matches))
        if len(matches) != 1 or not matches[0].is_file():
            raise VideoNarrationSynthesisError(
                "Live2D model reference must resolve to one file inside a trusted root.",
                retryable=False,
            )
        model_path = matches[0]
        if not model_path.name.endswith(".model.json") or model_path.name.endswith(
            ".model3.json"
        ):
            raise VideoNarrationSynthesisError(
                "The configured DSakiko adapter currently requires a Cubism 2 .model.json file.",
                retryable=False,
            )
        return model_path

    @staticmethod
    def _model_tree_sha256(model_path: Path) -> str:
        with model_path.open("r", encoding="utf-8") as json_handle:
            payload = json.load(json_handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
            raise VideoNarrationSynthesisError(
                "Live2D model JSON is not a valid Cubism 2 descriptor.",
                retryable=False,
            )

        references: set[Path] = {model_path}
        parent = model_path.parent.resolve(strict=True)

        def collect(value: object) -> None:
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str) and Path(value).suffix.lower() in {
                ".json",
                ".moc",
                ".mtn",
                ".png",
            }:
                path = (parent / value).resolve(strict=True)
                if not path.is_relative_to(parent) or not path.is_file():
                    raise VideoNarrationSynthesisError(
                        "Live2D model references an unsafe or missing local asset.",
                        retryable=False,
                    )
                references.add(path)

        collect(payload)
        digest = hashlib.sha256()
        for path in sorted(references, key=lambda item: item.relative_to(parent).as_posix()):
            relative = path.relative_to(parent).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            with path.open("rb") as asset_handle:
                for chunk in iter(lambda: asset_handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _file_evidence(path: Path) -> tuple[int, str]:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise VideoNarrationSynthesisError("Live2D worker output is not a regular file.")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise VideoNarrationSynthesisError("Live2D worker output changed during hashing.")
        return before.st_size, digest.hexdigest()

    @staticmethod
    def _resolve_executable(value: str | Path, label: str) -> str:
        raw = str(value)
        resolved = shutil.which(raw)
        if resolved is None:
            candidate = Path(raw).expanduser()
            if candidate.is_file():
                resolved = str(candidate.resolve())
        if resolved is None:
            raise ValueError(f"{label} executable is unavailable")
        return resolved
