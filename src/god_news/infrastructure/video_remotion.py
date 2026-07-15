from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

from god_news.domain.models import utc_now
from god_news.domain.video import (
    RemotionVideoProps,
    VideoInputAsset,
    VideoOutputProfile,
    VideoRenderArtifact,
    VideoRenderOutput,
)
from god_news.infrastructure.processes import (
    attach_kill_on_close_job,
    close_kill_on_close_job,
    sanitized_subprocess_env,
    terminate_process_tree,
)
from god_news.video_errors import VideoRendererUnavailableError, VideoRenderingError

logger = logging.getLogger(__name__)


class LocalRemotionBatchVideoRenderer:
    """Process-isolated adapter around the repository-owned Remotion renderer.

    One reviewed semantic snapshot is rendered for every declared output
    profile. Outputs are published atomically as a set: a failed profile removes
    the whole attempt, so a batch can be retried without mistaking partial files
    for approved artifacts.
    """

    def __init__(
        self,
        *,
        package_dir: Path,
        output_dir: Path,
        node_command: str,
        timeout_seconds: float,
        max_parallel_batches: int,
        concurrency: int,
    ) -> None:
        self._package_dir = package_dir.expanduser().resolve(strict=False)
        self._output_dir = output_dir.expanduser().resolve(strict=False)
        self._node = self._resolve_command(node_command)
        self._tsx_cli = self._package_dir / "node_modules" / "tsx" / "dist" / "cli.mjs"
        self._render_script = self._package_dir / "scripts" / "render.ts"
        self._ffprobe = self._discover_ffprobe(self._package_dir.parent)
        self._timeout_seconds = timeout_seconds
        self._batch_slots = asyncio.Semaphore(max_parallel_batches)
        self._concurrency = concurrency

    @property
    def name(self) -> str:
        return "local-remotion"

    def readiness_error(self) -> str | None:
        missing = [
            str(path)
            for path in (self._tsx_cli, self._render_script)
            if not path.is_file()
        ]
        if missing:
            return f"Remotion package files are missing: {', '.join(missing)}"
        if self._ffprobe is None:
            return "Remotion's bundled ffprobe executable was not found."
        return None

    async def cleanup_interrupted(self, batch_ids: Sequence[UUID]) -> int:
        attempts: list[Path] = []
        for batch_id in batch_ids:
            batch_root = self._trusted_batch_root(batch_id)
            if batch_root is None or not batch_root.is_dir():
                continue
            for path in batch_root.glob("attempt-*"):
                resolved = path.resolve(strict=False)
                if (
                    not path.is_dir()
                    or resolved != path.absolute()
                    or resolved.parent != batch_root
                ):
                    logger.warning(
                        "Skipped unsafe interrupted render path for batch %s.",
                        batch_id,
                    )
                    continue
                attempts.append(path)
        for path in attempts:
            await asyncio.to_thread(shutil.rmtree, path, True)
        return len(attempts)

    async def render(
        self,
        batch_id: UUID,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> VideoRenderArtifact:
        async with self._batch_slots:
            return await self._render_exclusive(batch_id, props, input_assets)

    async def _render_exclusive(
        self,
        batch_id: UUID,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> VideoRenderArtifact:
        readiness_error = self.readiness_error()
        if readiness_error is not None:
            raise VideoRendererUnavailableError(readiness_error)

        batch_root = self._trusted_batch_root(batch_id)
        if batch_root is None or (batch_root.exists() and not batch_root.is_dir()):
            raise VideoRenderingError(
                "The configured render batch directory is not a safe local directory.",
                retryable=False,
            )
        await asyncio.to_thread(batch_root.mkdir, parents=True, exist_ok=True)
        if self._trusted_batch_root(batch_id) != batch_root:
            raise VideoRenderingError(
                "The render batch directory changed while it was being prepared.",
                retryable=False,
            )
        attempt = Path(
            await asyncio.to_thread(
                tempfile.mkdtemp,
                prefix="attempt-",
                dir=batch_root,
            )
        )
        resolved_attempt, absolute_attempt = await asyncio.to_thread(
            lambda: (attempt.resolve(strict=False), attempt.absolute())
        )
        if resolved_attempt.parent != batch_root or resolved_attempt != absolute_attempt:
            raise VideoRenderingError(
                "The render attempt directory escaped its configured batch root.",
                retryable=False,
            )
        try:
            staged_props = await asyncio.to_thread(
                self._stage_verified_inputs,
                attempt,
                props,
                input_assets,
            )
            props_path = attempt / "render-props.json"
            await asyncio.to_thread(
                props_path.write_text,
                staged_props.model_dump_json(),
                encoding="utf-8",
            )
            outputs = []
            for profile in staged_props.output_profiles:
                outputs.append(await self._render_profile(props_path, attempt, profile))
            await asyncio.to_thread(props_path.unlink, missing_ok=True)
            return VideoRenderArtifact(
                renderer=self.name,
                outputs=outputs,
                rendered_at=utc_now(),
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(shutil.rmtree, attempt, True)
            raise
        except (VideoRenderingError, VideoRendererUnavailableError):
            await asyncio.to_thread(shutil.rmtree, attempt, True)
            raise
        except Exception as exc:
            await asyncio.to_thread(shutil.rmtree, attempt, True)
            raise VideoRenderingError("The local Remotion renderer failed unexpectedly.") from exc

    @classmethod
    def _stage_verified_inputs(
        cls,
        attempt: Path,
        props: RemotionVideoProps,
        input_assets: Sequence[VideoInputAsset],
    ) -> RemotionVideoProps:
        """Copy the approved bytes once and point every profile at that snapshot."""

        staged_root = attempt / "approved-inputs"
        staged_root.mkdir(parents=True, exist_ok=False)
        staged_by_source: dict[str, str] = {}
        for index, asset in enumerate(input_assets):
            source = Path(asset.local_path).expanduser().resolve(strict=True)
            suffix = source.suffix.lower() or ".bin"
            destination = staged_root / (
                f"{index:03d}-{asset.kind.value}-{asset.sha256}{suffix}"
            )
            cls._copy_verified_input(source, destination, asset)
            staged_by_source[str(source)] = str(destination)

        def staged_path(value: str) -> str:
            source = str(Path(value).expanduser().resolve(strict=True))
            try:
                return staged_by_source[source]
            except KeyError as exc:
                raise VideoRenderingError(
                    "Render props reference an input outside the approved asset snapshot.",
                    retryable=False,
                ) from exc

        manifest = props.manifest.model_copy(
            update={
                "timeline": [
                    segment.model_copy(update={"audio_path": staged_path(segment.audio_path)})
                    for segment in props.manifest.timeline
                ]
            }
        )
        bgm = (
            props.bgm.model_copy(update={"local_path": staged_path(props.bgm.local_path)})
            if props.bgm is not None
            else None
        )
        source_videos = [
            asset.model_copy(update={"local_path": staged_path(asset.local_path)})
            for asset in props.source_videos
        ]
        return props.model_copy(
            update={"manifest": manifest, "bgm": bgm, "source_videos": source_videos}
        )

    @staticmethod
    def _copy_verified_input(
        source: Path,
        destination: Path,
        expected: VideoInputAsset,
    ) -> None:
        temporary = destination.with_suffix(f"{destination.suffix}.partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
                    size += len(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if size != expected.size_bytes or digest.hexdigest() != expected.sha256:
                raise VideoRenderingError(
                    "An approved render input changed while its snapshot was being created.",
                    retryable=False,
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    async def _render_profile(
        self,
        props_path: Path,
        attempt: Path,
        profile: VideoOutputProfile,
    ) -> VideoRenderOutput:
        output_path = attempt / f"{profile.profile_id.value}.mp4"
        command = [
            self._node,
            str(self._tsx_cli),
            str(self._render_script),
            "--input",
            str(props_path),
            "--profile",
            profile.profile_id.value,
            "--output",
            str(output_path),
            "--concurrency",
            str(self._concurrency),
        ]
        stdout = await self._run(command, cwd=self._package_dir)
        result = self._last_json_object(stdout)
        expected = {
            "profile_id": profile.profile_id.value,
            "width": profile.width,
            "height": profile.height,
            "fps": profile.fps,
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise VideoRenderingError(
                f"Remotion returned inconsistent metadata for {profile.profile_id.value}.",
                retryable=False,
            )
        duration_in_frames = result.get("duration_in_frames")
        if not isinstance(duration_in_frames, int) or duration_in_frames <= 0:
            raise VideoRenderingError(
                "Remotion returned an invalid frame duration.",
                retryable=False,
            )
        if not output_path.is_file():
            raise VideoRenderingError("Remotion exited without producing its declared MP4.")

        probe = await self._probe(output_path)
        video = probe["video"]
        audio = probe["audio"]
        if video.get("width") != profile.width or video.get("height") != profile.height:
            raise VideoRenderingError(
                f"Rendered dimensions do not match {profile.profile_id.value}.",
                retryable=False,
            )
        probed_fps = self._parse_fps(video.get("r_frame_rate"))
        if probed_fps != profile.fps:
            raise VideoRenderingError("Rendered frame rate does not match the output profile.")

        size_bytes, digest = await asyncio.to_thread(self._file_evidence, output_path)
        return VideoRenderOutput(
            profile_id=profile.profile_id,
            local_path=str(output_path),
            size_bytes=size_bytes,
            sha256=digest,
            width=profile.width,
            height=profile.height,
            fps=profile.fps,
            duration_in_frames=duration_in_frames,
            video_codec=str(video["codec_name"]),
            audio_codec=str(audio["codec_name"]),
        )

    async def _probe(self, output_path: Path) -> dict[str, dict[str, Any]]:
        assert self._ffprobe is not None
        stdout = await self._run(
            [
                str(self._ffprobe),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate",
                "-of",
                "json",
                str(output_path),
            ],
            cwd=self._package_dir,
        )
        try:
            payload = json.loads(stdout)
            streams = payload["streams"]
            video = next(stream for stream in streams if stream.get("codec_type") == "video")
            audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
        except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
            raise VideoRenderingError(
                "Rendered MP4 is missing a decodable video or audio stream.",
                retryable=False,
            ) from exc
        return {"video": video, "audio": audio}

    async def _run(self, command: list[str], *, cwd: Path) -> str:
        creationflags = 0
        if os.name == "nt":
            creationflags = 0x08000000 | 0x00000200
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=sanitized_subprocess_env(),
            creationflags=creationflags,
        )
        job_handle = await asyncio.to_thread(attach_kill_on_close_job, process.pid)
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
            await asyncio.to_thread(close_kill_on_close_job, job_handle)
        if process.returncode != 0:
            stderr_digest = hashlib.sha256(stderr).hexdigest()
            logger.error(
                "Local media worker failed (exit_code=%s, stderr_sha256=%s).",
                process.returncode,
                stderr_digest,
            )
            raise VideoRenderingError(
                f"Local media worker exited with code {process.returncode}."
            )
        return stdout.decode("utf-8", errors="strict")

    @staticmethod
    def _last_json_object(output: str) -> dict[str, Any]:
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise VideoRenderingError("Remotion did not return its structured result.")

    @staticmethod
    def _parse_fps(value: object) -> Fraction:
        if not isinstance(value, str):
            raise VideoRenderingError("ffprobe returned an invalid frame rate.")
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise VideoRenderingError("ffprobe returned an invalid frame rate.") from exc

    @staticmethod
    def _file_evidence(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        if size <= 0:
            raise VideoRenderingError("Remotion produced an empty output file.")
        return size, digest.hexdigest()

    @staticmethod
    def _resolve_command(command: str) -> str:
        resolved = shutil.which(command)
        if resolved is None:
            raise VideoRendererUnavailableError(f"Required command is not available: {command}")
        return resolved

    def _trusted_batch_root(self, batch_id: UUID) -> Path | None:
        """Resolve one direct child, rejecting symlink and NTFS junction escapes."""

        root = self._output_dir.resolve(strict=False)
        candidate = self._output_dir / str(batch_id)
        resolved = candidate.resolve(strict=False)
        expected = root / str(batch_id)
        return resolved if resolved == expected else None

    @staticmethod
    def _discover_ffprobe(workspace: Path) -> Path | None:
        executable = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        system = shutil.which(executable)
        if system is not None:
            return Path(system).resolve()
        pnpm_root = workspace / "node_modules" / ".pnpm"
        if not pnpm_root.is_dir():
            return None
        matches = sorted(
            path.resolve()
            for path in pnpm_root.glob(
                f"@remotion+compositor-*/node_modules/@remotion/compositor-*/{executable}"
            )
            if path.is_file()
        )
        return matches[-1] if matches else None
