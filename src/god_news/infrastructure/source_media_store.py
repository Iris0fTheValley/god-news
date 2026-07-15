from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterable
from pathlib import Path, PurePosixPath
from uuid import UUID

from god_news.domain.source_media import SourceMediaStore
from god_news.errors import SourceMediaAcquisitionError

_MP4_CONTENT_TYPES = frozenset({"video/mp4", "application/mp4", "application/octet-stream"})


class LocalSourceMediaStore(SourceMediaStore):
    def __init__(self, root: Path, *, max_download_bytes: int) -> None:
        if max_download_bytes <= 0:
            raise ValueError("max_download_bytes must be positive")
        self._root = root.expanduser().resolve(strict=False)
        self._max_download_bytes = max_download_bytes

    async def write(
        self,
        *,
        story_id: UUID,
        artifact_id: UUID,
        content_type: str,
        body: AsyncIterable[bytes],
    ) -> tuple[str, str, int, Path]:
        normalized_type = content_type.partition(";")[0].strip().casefold()
        if normalized_type not in _MP4_CONTENT_TYPES:
            raise SourceMediaAcquisitionError(
                story_id,
                "Source media response is not a supported MP4 payload.",
            )
        storage_key = (PurePosixPath(str(story_id)) / f"{artifact_id}.mp4").as_posix()
        target = self._path_for_key(storage_key)
        temporary = target.with_suffix(".partial")
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        header = bytearray()
        try:
            handle = await asyncio.to_thread(temporary.open, "xb")
            try:
                async for chunk in body:
                    if not isinstance(chunk, bytes):
                        raise SourceMediaAcquisitionError(
                            story_id,
                            "Source media stream returned malformed bytes.",
                        )
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self._max_download_bytes:
                        raise SourceMediaAcquisitionError(
                            story_id,
                            "Source media exceeds the configured download limit.",
                            status_code=413,
                        )
                    if len(header) < 32:
                        header.extend(chunk[: 32 - len(header)])
                    digest.update(chunk)
                    await asyncio.to_thread(handle.write, chunk)
                await asyncio.to_thread(handle.flush)
                await asyncio.to_thread(os.fsync, handle.fileno())
            finally:
                await asyncio.to_thread(handle.close)
            if size <= 0 or not _looks_like_mp4(bytes(header)):
                raise SourceMediaAcquisitionError(
                    story_id,
                    "Source media bytes do not contain an MP4 file signature.",
                )
            await asyncio.to_thread(os.replace, temporary, target)
        except SourceMediaAcquisitionError:
            await asyncio.to_thread(_remove_if_file, temporary)
            raise
        except (FileExistsError, OSError) as exc:
            await asyncio.to_thread(_remove_if_file, temporary)
            raise SourceMediaAcquisitionError(
                story_id,
                "Source media could not be stored safely.",
                status_code=500,
                retryable=True,
            ) from exc
        return storage_key, digest.hexdigest(), size, target

    async def remove(self, storage_key: str) -> None:
        await asyncio.to_thread(_remove_if_file, self._path_for_key(storage_key))

    async def resolve_verified(
        self,
        storage_key: str,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Path:
        path = self._path_for_key(storage_key)
        resolved = await asyncio.to_thread(path.resolve, strict=True)
        if not resolved.is_relative_to(self._root) or not resolved.is_file():
            raise ValueError("source media storage key is not a regular file")
        size_bytes, digest = await asyncio.to_thread(_file_evidence, resolved)
        if (size_bytes, digest) != (expected_size_bytes, expected_sha256):
            raise ValueError("source media file no longer matches its immutable evidence")
        return resolved

    def _path_for_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or any(part in {"", ".", ".."} for part in key.parts)
            or "\\" in storage_key
        ):
            raise ValueError("source media storage key is invalid")
        candidate = self._root.joinpath(*key.parts)
        if not candidate.resolve(strict=False).is_relative_to(self._root):
            raise ValueError("source media storage key escapes its root")
        return candidate


def _looks_like_mp4(header: bytes) -> bool:
    return len(header) >= 12 and header[4:8] == b"ftyp"


def _remove_if_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        return


def _file_evidence(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return size_bytes, digest.hexdigest()
