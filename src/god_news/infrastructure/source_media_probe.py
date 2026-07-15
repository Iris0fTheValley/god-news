from __future__ import annotations

import asyncio
import json
import os
import shutil
from fractions import Fraction
from pathlib import Path

from god_news.domain.source_media import SourceVideoInspector, SourceVideoProbe
from god_news.infrastructure.processes import sanitized_subprocess_env, terminate_process_tree


class FFprobeSourceVideoInspector(SourceVideoInspector):
    def __init__(self, executable: str | Path, *, timeout_seconds: float = 30) -> None:
        resolved = shutil.which(str(executable))
        if resolved is None and Path(executable).is_file():
            resolved = str(Path(executable).resolve())
        if resolved is None:
            raise ValueError("ffprobe executable is unavailable")
        self._executable = resolved
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def discover(workspace: Path) -> Path | None:
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

    async def inspect(self, path: Path) -> SourceVideoProbe:
        creationflags = 0x08000000 | 0x00000200 if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            self._executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=sanitized_subprocess_env(),
            creationflags=creationflags,
        )
        try:
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout_seconds,
                )
            except (TimeoutError, asyncio.CancelledError):
                await asyncio.shield(terminate_process_tree(process))
                raise
        finally:
            if process.returncode is None:
                await asyncio.shield(terminate_process_tree(process))
        if process.returncode != 0:
            raise ValueError("ffprobe rejected the downloaded source media")
        try:
            payload = json.loads(stdout.decode("utf-8", errors="strict"))
            streams = payload["streams"]
            video = next(stream for stream in streams if stream.get("codec_type") == "video")
            audio = next(
                (stream for stream in streams if stream.get("codec_type") == "audio"),
                None,
            )
            duration_ms = round(float(payload["format"]["duration"]) * 1_000)
            fps = float(Fraction(str(video["r_frame_rate"])))
            return SourceVideoProbe(
                duration_ms=duration_ms,
                width=int(video["width"]),
                height=int(video["height"]),
                video_codec=str(video["codec_name"]),
                audio_codec=(str(audio["codec_name"]) if audio is not None else None),
                fps=fps,
            )
        except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("ffprobe returned invalid source media metadata") from exc
