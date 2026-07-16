from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterable
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from god_news.domain.visual_assets import ImageContentType
from god_news.errors import VisualAssetStorageError, VisualAssetUploadError

_SUFFIX_BY_CONTENT_TYPE = {
    ImageContentType.PNG: ".png",
    ImageContentType.JPEG: ".jpg",
    ImageContentType.WEBP: ".webp",
}
_MAX_IMAGE_DIMENSION = 16_384
_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)


class LocalVisualAssetStore:
    """Small, path-contained store for operator-provided raster images.

    The service never trusts a filename for path construction.  It buffers at
    most the configured upload limit, checks the declared raster format against
    signature bytes, writes to a same-directory temporary file, then replaces
    atomically.  The returned key is relative to this store and can safely be
    persisted without exposing a host path through the public API.
    """

    def __init__(self, root: Path, *, max_upload_bytes: int, max_pixels: int) -> None:
        self._root = root.expanduser().resolve(strict=False)
        self._max_upload_bytes = max_upload_bytes
        self._max_pixels = max_pixels

    async def write(
        self,
        *,
        story_id: UUID,
        asset_id: UUID,
        content_type: ImageContentType,
        body: AsyncIterable[bytes],
    ) -> tuple[str, str, int]:
        content = bytearray()
        async for chunk in body:
            if not isinstance(chunk, bytes):
                raise VisualAssetUploadError(story_id, "Image upload body is malformed.")
            if not chunk:
                continue
            if len(content) + len(chunk) > self._max_upload_bytes:
                raise VisualAssetUploadError(
                    story_id,
                    f"Image upload exceeds the {self._max_upload_bytes} byte limit.",
                    status_code=413,
                )
            content.extend(chunk)

        raw = bytes(content)
        if not raw:
            raise VisualAssetUploadError(story_id, "Image upload is empty.")
        try:
            width, height = _parse_image_dimensions(content_type, raw)
        except ValueError as exc:
            raise VisualAssetUploadError(
                story_id,
                "Image bytes do not match the declared supported raster format.",
            ) from exc
        if width * height > self._max_pixels:
            raise VisualAssetUploadError(
                story_id,
                f"Image dimensions exceed the {self._max_pixels} pixel limit.",
            )

        suffix = _SUFFIX_BY_CONTENT_TYPE[content_type]
        storage_key = (PurePosixPath(str(story_id)) / f"{asset_id}{suffix}").as_posix()
        target = self._path_for_key(storage_key)
        digest = hashlib.sha256(raw).hexdigest()
        try:
            await asyncio.to_thread(_atomic_write, target, raw)
        except OSError as exc:
            raise VisualAssetStorageError(story_id) from exc
        return storage_key, digest, len(raw)

    async def remove(self, storage_key: str) -> None:
        path = self._path_for_key(storage_key)
        try:
            await asyncio.to_thread(_remove_if_regular_file, path)
        except OSError:
            # The DB binding has already moved on. Retention can collect a
            # rare orphan later, so a failed best-effort cleanup is not a
            # reason to roll back a durable replacement.
            return

    async def resolve(self, storage_key: str) -> Path:
        path = self._path_for_key(storage_key)
        return await asyncio.to_thread(_resolve_regular_file, self._root, path)

    def _path_for_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or any(part in {"", ".", ".."} for part in key.parts)
            or "\\" in storage_key
        ):
            raise ValueError("visual asset storage key is invalid")
        candidate = self._root.joinpath(*key.parts)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise ValueError("visual asset storage key escapes its root")
        return candidate


async def inspect_raster_dimensions(
    path: Path,
    content_type: ImageContentType,
) -> tuple[int, int]:
    payload = await asyncio.to_thread(path.read_bytes)
    return _parse_image_dimensions(content_type, payload)


def _parse_image_dimensions(content_type: ImageContentType, payload: bytes) -> tuple[int, int]:
    if content_type is ImageContentType.PNG:
        return _parse_png_dimensions(payload)
    if content_type is ImageContentType.JPEG:
        return _parse_jpeg_dimensions(payload)
    if content_type is ImageContentType.WEBP:
        return _parse_webp_dimensions(payload)
    raise ValueError("unsupported image content type")


def _parse_png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 45 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a complete PNG")
    position = 8
    width = height = 0
    saw_ihdr = saw_idat = saw_iend = False
    while position < len(payload):
        if position + 12 > len(payload):
            raise ValueError("truncated PNG chunk")
        length = int.from_bytes(payload[position : position + 4], "big")
        chunk_type = payload[position + 4 : position + 8]
        data_start = position + 8
        data_end = data_start + length
        chunk_end = data_end + 4
        if chunk_end > len(payload):
            raise ValueError("PNG chunk exceeds payload")
        if not saw_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG must begin with IHDR")
            width = int.from_bytes(payload[data_start : data_start + 4], "big")
            height = int.from_bytes(payload[data_start + 4 : data_start + 8], "big")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0 or chunk_end != len(payload):
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            break
        position = chunk_end
    if not (saw_ihdr and saw_idat and saw_iend):
        raise ValueError("PNG has no complete image data")
    return _validate_dimensions(width, height)


def _parse_jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    if (
        len(payload) < 12
        or not payload.startswith(b"\xff\xd8")
        or not payload.endswith(b"\xff\xd9")
    ):
        raise ValueError("not a complete JPEG")
    position = 2
    dimensions: tuple[int, int] | None = None
    while position < len(payload) - 2:
        while position < len(payload) and payload[position] == 0xFF:
            position += 1
        if position >= len(payload):
            raise ValueError("truncated JPEG marker")
        marker = payload[position]
        position += 1
        if marker in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
            continue
        if position + 2 > len(payload):
            raise ValueError("truncated JPEG segment")
        segment_length = int.from_bytes(payload[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(payload):
            raise ValueError("invalid JPEG segment length")
        segment_start = position + 2
        segment_end = position + segment_length
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 8:
                raise ValueError("truncated JPEG frame header")
            height = int.from_bytes(payload[segment_start + 1 : segment_start + 3], "big")
            width = int.from_bytes(payload[segment_start + 3 : segment_start + 5], "big")
            dimensions = _validate_dimensions(width, height)
        if marker == 0xDA:
            if dimensions is None:
                raise ValueError("JPEG scan appears before frame dimensions")
            return dimensions
        position = segment_end
    raise ValueError("JPEG has no image scan")


def _parse_webp_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 20 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        raise ValueError("not a WebP RIFF payload")
    declared_size = int.from_bytes(payload[4:8], "little")
    if declared_size != len(payload) - 8:
        raise ValueError("WebP RIFF size does not match payload")
    position = 12
    canvas_dimensions: tuple[int, int] | None = None
    frame_dimensions: tuple[int, int] | None = None
    while position < len(payload):
        if position + 8 > len(payload):
            raise ValueError("truncated WebP chunk")
        chunk_type = payload[position : position + 4]
        chunk_length = int.from_bytes(payload[position + 4 : position + 8], "little")
        data_start = position + 8
        data_end = data_start + chunk_length
        if data_end > len(payload):
            raise ValueError("WebP chunk exceeds payload")
        chunk = payload[data_start:data_end]
        if chunk_type == b"VP8X":
            if len(chunk) != 10:
                raise ValueError("invalid VP8X header")
            canvas_dimensions = _validate_dimensions(
                int.from_bytes(chunk[4:7], "little") + 1,
                int.from_bytes(chunk[7:10], "little") + 1,
            )
        elif chunk_type == b"VP8 ":
            if len(chunk) < 10 or chunk[3:6] != b"\x9d\x01\x2a":
                raise ValueError("invalid VP8 frame header")
            frame_dimensions = _validate_dimensions(
                int.from_bytes(chunk[6:8], "little") & 0x3FFF,
                int.from_bytes(chunk[8:10], "little") & 0x3FFF,
            )
        elif chunk_type == b"VP8L":
            if len(chunk) < 5 or chunk[0] != 0x2F:
                raise ValueError("invalid VP8L frame header")
            bits = int.from_bytes(chunk[1:5], "little")
            frame_dimensions = _validate_dimensions(
                (bits & 0x3FFF) + 1,
                ((bits >> 14) & 0x3FFF) + 1,
            )
        position = data_end + (chunk_length % 2)
    if position != len(payload) or frame_dimensions is None:
        raise ValueError("WebP has no complete image frame")
    if canvas_dimensions is None:
        return frame_dimensions
    if (
        frame_dimensions[0] > canvas_dimensions[0]
        or frame_dimensions[1] > canvas_dimensions[1]
    ):
        raise ValueError("WebP frame exceeds its canvas")
    return canvas_dimensions


def _validate_dimensions(width: int, height: int) -> tuple[int, int]:
    if not (0 < width <= _MAX_IMAGE_DIMENSION and 0 < height <= _MAX_IMAGE_DIMENSION):
        raise ValueError("image dimensions are out of bounds")
    return width, height


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_if_regular_file(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    if not path.is_file() or path.is_symlink():
        return
    path.unlink()


def _resolve_regular_file(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise OSError("symbolic links cannot be served as visual assets")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise OSError("visual asset is not a regular file under the configured root")
    return resolved
