from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import httpx


class VisualDiscoveryDownloadError(ValueError):
    pass


class LocalVisualDiscoveryStore:
    """Streaming, path-contained storage for provider-selected Commons originals."""

    def __init__(self, root: Path, *, max_download_bytes: int) -> None:
        self._root = root.expanduser().resolve(strict=False)
        self._max_download_bytes = max_download_bytes

    async def write_download(
        self,
        *,
        asset_id: UUID,
        filename: str,
        response: object,
        expected_max_bytes: int,
    ) -> tuple[str, str, int, Path]:
        if not isinstance(response, httpx.Response):
            raise VisualDiscoveryDownloadError("download response is invalid")
        limit = min(self._max_download_bytes, expected_max_bytes)
        if response.status_code != 200:
            raise VisualDiscoveryDownloadError("Commons download did not return 200")
        header_size = response.headers.get("content-length")
        if header_size is not None and (not header_size.isdecimal() or int(header_size) > limit):
            raise VisualDiscoveryDownloadError("Commons download exceeds configured byte limit")
        suffix = _safe_suffix(filename)
        key = (PurePosixPath("commons") / str(asset_id) / f"original{suffix}").as_posix()
        target = self._path_for_key(key)
        digest = hashlib.sha256()
        total = 0
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as handle:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > limit:
                        raise VisualDiscoveryDownloadError(
                            "Commons download exceeds configured byte limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                if total == 0:
                    raise VisualDiscoveryDownloadError("Commons download was empty")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
        return key, digest.hexdigest(), total, target

    async def resolve(self, storage_key: str) -> Path:
        path = self._path_for_key(storage_key)
        return await asyncio.to_thread(_resolve_regular_file, self._root, path)

    async def clone(
        self,
        *,
        source_storage_key: str,
        target_asset_id: UUID,
        filename: str,
    ) -> tuple[str, str, int, Path]:
        source = await self.resolve(source_storage_key)
        suffix = _safe_suffix(filename)
        key = (
            PurePosixPath("commons") / str(target_asset_id) / f"original{suffix}"
        ).as_posix()
        target = self._path_for_key(key)
        digest, size = await asyncio.to_thread(
            _atomic_clone,
            source,
            target,
            self._max_download_bytes,
        )
        return key, digest, size, target

    async def remove(self, storage_key: str) -> None:
        path = self._path_for_key(storage_key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            await asyncio.to_thread(path.parent.rmdir)
        except OSError:
            return

    def _path_for_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or "\\" in storage_key
            or any(part in {"", ".", ".."} for part in key.parts)
        ):
            raise ValueError("visual discovery storage key is invalid")
        candidate = self._root.joinpath(*key.parts)
        if not candidate.resolve(strict=False).is_relative_to(self._root):
            raise ValueError("visual discovery storage escaped its root")
        return candidate


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.casefold()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return ".bin"
    return suffix


def _resolve_regular_file(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise OSError("symbolic links are not valid Commons assets")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise OSError("Commons asset is not a regular file under its root")
    return resolved


def _atomic_clone(source: Path, target: Path, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=False)
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise VisualDiscoveryDownloadError(
                        "Commons clone exceeds configured byte limit"
                    )
                digest.update(chunk)
                writer.write(chunk)
            if size == 0:
                raise VisualDiscoveryDownloadError("Commons clone source was empty")
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        try:
            target.parent.rmdir()
        except OSError:
            pass
        raise
    return digest.hexdigest(), size
