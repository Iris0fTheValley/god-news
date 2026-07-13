from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.application.video_batches import VideoBatchService
from god_news.container import AppContainer
from god_news.domain.video import (
    BgmTrack,
    CreateVideoBatch,
    RenderVideoBatch,
    SubmitNarrationReview,
    SubmitTimelineReview,
    SynthesizeBatchNarration,
    VideoBatch,
    VideoBatchStatus,
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


@router.get(
    "/bgm",
    response_model=list[BgmTrack],
    operation_id="listLocalBgmTracks",
)
async def list_bgm(service: VideoBatchServiceDependency) -> list[BgmTrack]:
    return list(await service.list_bgm())


@router.post(
    "/batches",
    response_model=VideoBatch,
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
    response_model=list[VideoBatch],
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
    response_model=VideoBatch,
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


@router.post(
    "/batches/{batch_id}/narration-review",
    response_model=VideoBatch,
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
    response_model=VideoBatch,
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
    response_model=VideoBatch,
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
    response_model=VideoBatch,
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
    response_model=VideoBatch,
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
