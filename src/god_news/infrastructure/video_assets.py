from __future__ import annotations

import asyncio
import builtins
import hashlib
from collections.abc import Sequence
from pathlib import Path

from god_news.domain.video import BgmSelection, BgmTrack
from god_news.video_errors import BgmTrackNotFoundError


class LocalBgmCatalog:
    def __init__(
        self,
        root: Path,
        *,
        allowed_extensions: Sequence[str] = (".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"),
    ) -> None:
        self._root = root.expanduser().resolve()
        self._extensions = frozenset(extension.casefold() for extension in allowed_extensions)
        if not self._extensions or any(not item.startswith(".") for item in self._extensions):
            raise ValueError("allowed BGM extensions must be non-empty dot-prefixed suffixes")

    async def list(self) -> Sequence[BgmTrack]:
        return await asyncio.to_thread(self._scan)

    async def resolve(
        self,
        track_id: str,
        *,
        volume: float,
        loop: bool,
    ) -> BgmSelection:
        tracks = await asyncio.to_thread(self._scan_with_paths)
        match = next(((track, path) for track, path in tracks if track.track_id == track_id), None)
        if match is None:
            raise BgmTrackNotFoundError(track_id)
        track, path = match
        return BgmSelection(
            track_id=track.track_id,
            local_path=str(path),
            volume=volume,
            loop=loop,
        )

    def _scan(self) -> builtins.list[BgmTrack]:
        return [track for track, _ in self._scan_with_paths()]

    def _scan_with_paths(self) -> builtins.list[tuple[BgmTrack, Path]]:
        if not self._root.is_dir():
            return []
        result: builtins.list[tuple[BgmTrack, Path]] = []
        for candidate in self._root.rglob("*"):
            if candidate.suffix.casefold() not in self._extensions:
                continue
            try:
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(self._root)
            except (OSError, ValueError):
                continue
            if not resolved.is_file():
                continue
            size = resolved.stat().st_size
            if size <= 0:
                continue
            relative_text = relative.as_posix()
            digest = hashlib.sha256()
            digest.update(relative_text.encode("utf-8"))
            digest.update(b"\0")
            try:
                with resolved.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            track_id = digest.hexdigest()
            result.append(
                (
                    BgmTrack(
                        track_id=track_id,
                        relative_path=relative_text,
                        display_name=relative.stem,
                        size_bytes=size,
                    ),
                    resolved,
                )
            )
        result.sort(key=lambda item: (item[0].relative_path.casefold(), item[0].relative_path))
        return result
