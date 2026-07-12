from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from god_news.api.dependencies import get_container
from god_news.application.video_batches import VideoBatchService
from god_news.container import AppContainer
from god_news.domain.video import (
    BgmTrack,
    CreateVideoBatch,
    RenderVideoBatch,
    SubmitTimelineReview,
    VideoBatch,
    VideoBatchStatus,
)
from god_news.video_errors import VideoRendererUnavailableError

router = APIRouter(prefix="/video", tags=["video"])
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
