from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.application.visual_assets import VisualAssetService
from god_news.container import AppContainer
from god_news.domain.visual_assets import (
    DeleteSegmentVisualAssetRequest,
    StoryVisualAssets,
    UploadSegmentVisualAssetRequest,
    VisualAssetMutation,
)
from god_news.errors import ConfigurationError

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail, "description": "Story or visual asset was not found."},
    409: {"model": ProblemDetail, "description": "Story version or script revision changed."},
    413: {"model": ProblemDetail, "description": "Image upload exceeds the configured limit."},
    422: {"model": ProblemDetail, "description": "Image upload or asset binding is invalid."},
    500: {"model": ProblemDetail, "description": "Local visual asset storage failed."},
    503: {"model": ProblemDetail, "description": "Visual asset service is not configured."},
}

router = APIRouter(tags=["visual-assets"], responses=PROBLEM_RESPONSES)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def get_visual_asset_service(container: ContainerDependency) -> VisualAssetService:
    if container.visual_assets is None:
        raise ConfigurationError("Visual asset service is not configured.")
    return container.visual_assets


VisualAssetServiceDependency = Annotated[VisualAssetService, Depends(get_visual_asset_service)]


@router.get(
    "/stories/{story_id}/visual-assets",
    response_model=StoryVisualAssets,
    operation_id="listStoryVisualAssets",
)
async def list_story_visual_assets(
    story_id: UUID,
    service: VisualAssetServiceDependency,
) -> StoryVisualAssets:
    return await service.list(story_id)


@router.put(
    "/stories/{story_id}/visual-assets/{segment_id}",
    response_model=VisualAssetMutation,
    operation_id="uploadSegmentVisualAsset",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}},
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def upload_segment_visual_asset(
    story_id: UUID,
    segment_id: UUID,
    request: Request,
    metadata: Annotated[UploadSegmentVisualAssetRequest, Query()],
    service: VisualAssetServiceDependency,
) -> VisualAssetMutation:
    """Replace one segment's image with a raw PNG, JPEG, or WebP request body."""

    return await service.upload_segment(
        story_id=story_id,
        segment_id=segment_id,
        request=metadata,
        declared_content_type=request.headers.get("content-type"),
        body=request.stream(),
    )


@router.delete(
    "/stories/{story_id}/visual-assets/{segment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteSegmentVisualAsset",
)
async def delete_segment_visual_asset(
    story_id: UUID,
    segment_id: UUID,
    request: Annotated[DeleteSegmentVisualAssetRequest, Query()],
    service: VisualAssetServiceDependency,
) -> Response:
    await service.delete_segment(
        story_id=story_id,
        segment_id=segment_id,
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/stories/{story_id}/visual-assets/{asset_id}/content",
    response_class=FileResponse,
    operation_id="getVisualAssetContent",
    responses={
        200: {
            "content": {
                "image/png": {},
                "image/jpeg": {},
                "image/webp": {},
            }
        }
    },
)
async def visual_asset_content(
    story_id: UUID,
    asset_id: UUID,
    service: VisualAssetServiceDependency,
) -> FileResponse:
    asset, path = await service.media_path(story_id, asset_id)
    return FileResponse(path, media_type=asset.content_type.value)
