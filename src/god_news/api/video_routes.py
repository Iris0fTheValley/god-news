from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, BinaryIO
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail, PublicVideoBatch
from god_news.application.video_batches import VideoBatchService
from god_news.container import AppContainer
from god_news.domain.video import (
    BgmTrack,
    CreateVideoBatch,
    LegacyVideoRenderArtifact,
    RenderVideoBatch,
    SubmitNarrationReview,
    SubmitTimelineReview,
    SynthesizeBatchNarration,
    VideoBatch,
    VideoBatchStatus,
    VideoOutputProfileId,
)
from god_news.video_errors import VideoBatchConflictError, VideoRendererUnavailableError

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ProblemDetail,
        "description": "Requested video batch or BGM track was not found.",
    },
    409: {
        "model": ProblemDetail,
        "description": "Video batch state, input evidence, or version conflict.",
    },
    422: {"model": ProblemDetail, "description": "Request validation failed."},
    502: {"model": ProblemDetail, "description": "Local video rendering failed."},
    503: {"model": ProblemDetail, "description": "Video orchestration or renderer is unavailable."},
}

router = APIRouter(prefix="/video", tags=["video"], responses=PROBLEM_RESPONSES)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def get_video_batch_service(container: ContainerDependency) -> VideoBatchService:
    if container.video_batches is None:
        raise VideoRendererUnavailableError("Video batch orchestration is not configured.")
    return container.video_batches


VideoBatchServiceDependency = Annotated[VideoBatchService, Depends(get_video_batch_service)]


def _open_regular_file_evidence(path: Path) -> tuple[BinaryIO, int, str] | None:
    handle: BinaryIO | None = None
    try:
        handle = path.open("rb")
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            handle.close()
            return None
        digest = hashlib.sha256()
        size = 0
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        handle.seek(0)
        return handle, size, digest.hexdigest()
    except OSError:
        if handle is not None:
            handle.close()
        return None


async def _stream_open_file(handle: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(handle.read, 1024 * 1024):
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


@router.get(
    "/bgm",
    response_model=list[BgmTrack],
    operation_id="listLocalBgmTracks",
)
async def list_bgm(service: VideoBatchServiceDependency) -> list[BgmTrack]:
    return list(await service.list_bgm())


@router.post(
    "/batches",
    response_model=PublicVideoBatch,
    status_code=201,
    operation_id="createVideoBatch",
)
async def create_video_batch(
    request: CreateVideoBatch,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.create(request)


@router.get(
    "/batches",
    response_model=list[PublicVideoBatch],
    operation_id="listVideoBatches",
)
async def list_video_batches(
    service: VideoBatchServiceDependency,
    status: VideoBatchStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VideoBatch]:
    batches = await service.list_batches(status=status, limit=limit, offset=offset)
    return list(batches)


@router.get(
    "/batches/{batch_id}",
    response_model=PublicVideoBatch,
    operation_id="getVideoBatch",
)
async def get_video_batch(
    batch_id: UUID,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.get(batch_id)


@router.get(
    "/batches/{batch_id}/audio/{segment_id}",
    response_class=FileResponse,
    operation_id="getVideoBatchAudioClip",
)
async def batch_audio_clip(
    batch_id: UUID,
    segment_id: UUID,
    container: ContainerDependency,
    service: VideoBatchServiceDependency,
) -> FileResponse:
    """Serve one reviewed batch-narration clip from the managed output root.

    The stored clip path is never trusted as a request path.  It must still
    resolve underneath the configured output root and refer to the exact
    segment persisted in the merged narration artifact.
    """

    batch = await service.get(batch_id)
    audio = batch.narration.audio
    if audio is None:
        raise VideoBatchConflictError("Batch narration audio is not ready.")
    clip = next((item for item in audio.clips if item.segment_id == segment_id), None)
    if clip is None:
        raise VideoBatchConflictError("Batch narration audio segment does not exist.")

    root = container.settings.output_dir.resolve()
    path = (root / Path(clip.path)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VideoBatchConflictError("Batch narration audio path is invalid.") from exc
    if not path.is_file():
        raise VideoBatchConflictError("Batch narration audio file is missing.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.get(
    "/batches/{batch_id}/outputs/{profile_id}",
    response_class=StreamingResponse,
    operation_id="getVideoBatchOutput",
)
async def batch_video_output(
    batch_id: UUID,
    profile_id: VideoOutputProfileId,
    container: ContainerDependency,
    service: VideoBatchServiceDependency,
) -> StreamingResponse:
    """Serve one verified render output without accepting or exposing a host path."""

    batch = await service.get(batch_id)
    if batch.artifact is None:
        raise VideoBatchConflictError("Video batch outputs are not ready.")
    if isinstance(batch.artifact, LegacyVideoRenderArtifact):
        raise VideoBatchConflictError(
            "This legacy batch predates platform render profiles and is retained read-only."
        )
    output = next(
        (item for item in batch.artifact.outputs if item.profile_id is profile_id),
        None,
    )
    if output is None:
        raise VideoBatchConflictError("The requested video output profile does not exist.")

    root = container.settings.video_render_root.resolve()
    path = await asyncio.to_thread(Path(output.local_path).resolve)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VideoBatchConflictError("Video output path is invalid.") from exc
    evidence = await asyncio.to_thread(_open_regular_file_evidence, path)
    if evidence is None:
        raise VideoBatchConflictError("Video output file is missing or changed.")
    handle, size_bytes, digest = evidence
    if (size_bytes, digest) != (output.size_bytes, output.sha256):
        await asyncio.to_thread(handle.close)
        raise VideoBatchConflictError("Video output file is missing or changed.")
    filename = f"{profile_id.value}.mp4"
    return StreamingResponse(
        _stream_open_file(handle),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(size_bytes),
        },
    )


@router.post(
    "/batches/{batch_id}/narration-review",
    response_model=PublicVideoBatch,
    operation_id="submitVideoBatchNarrationReview",
)
async def submit_video_batch_narration_review(
    batch_id: UUID,
    request: SubmitNarrationReview,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.submit_narration_review(batch_id, request)


@router.post(
    "/batches/{batch_id}/narration/synthesize",
    response_model=PublicVideoBatch,
    operation_id="synthesizeVideoBatchNarration",
)
async def synthesize_video_batch_narration(
    batch_id: UUID,
    request: SynthesizeBatchNarration,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.synthesize_narration(batch_id, request)


@router.post(
    "/batches/{batch_id}/timeline-review",
    response_model=PublicVideoBatch,
    operation_id="submitVideoTimelineReview",
)
async def submit_video_timeline_review(
    batch_id: UUID,
    request: SubmitTimelineReview,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.submit_timeline_review(batch_id, request)


@router.post(
    "/batches/{batch_id}/render",
    response_model=PublicVideoBatch,
    operation_id="renderVideoBatch",
)
async def render_video_batch(
    batch_id: UUID,
    request: RenderVideoBatch,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.render(
        batch_id,
        expected_version=request.expected_batch_version,
    )


@router.post(
    "/batches/{batch_id}/cancel",
    response_model=PublicVideoBatch,
    operation_id="cancelVideoRender",
)
async def cancel_video_render(
    batch_id: UUID,
    service: VideoBatchServiceDependency,
) -> VideoBatch:
    return await service.cancel(batch_id)


@router.delete(
    "/batches/{batch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteVideoBatch",
)
async def delete_video_batch(
    batch_id: UUID,
    service: VideoBatchServiceDependency,
) -> Response:
    await service.delete(batch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
