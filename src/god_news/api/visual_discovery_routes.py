from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.application.visual_discovery import VisualDiscoveryApplication
from god_news.container import AppContainer
from god_news.domain.visual_discovery import (
    CommonsDiscoveryRequest,
    CommonsDiscoveryResult,
    ReuseApprovedVisualRequest,
    StageCommonsVisualRequest,
    VisualDiscoveryAssetView,
    VisualDiscoveryReviewRequest,
)
from god_news.errors import ConfigurationError

router = APIRouter(
    tags=["visual-discovery"],
    responses={
        404: {"model": ProblemDetail},
        409: {"model": ProblemDetail},
        422: {"model": ProblemDetail},
        502: {"model": ProblemDetail},
        503: {"model": ProblemDetail},
    },
)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _service(container: ContainerDependency) -> VisualDiscoveryApplication:
    if container.visual_discovery is None:
        raise ConfigurationError("Visual discovery service is not configured.")
    return container.visual_discovery


ServiceDependency = Annotated[VisualDiscoveryApplication, Depends(_service)]


@router.get(
    "/visual-discovery/commons",
    response_model=CommonsDiscoveryResult,
    operation_id="searchCommonsVisuals",
)
async def search_commons_visuals(
    request: Annotated[CommonsDiscoveryRequest, Query()], service: ServiceDependency
) -> CommonsDiscoveryResult:
    return await service.search(request)


@router.post(
    "/visual-discovery/commons/stage",
    response_model=VisualDiscoveryAssetView,
    status_code=201,
    operation_id="stageCommonsVisual",
)
async def stage_commons_visual(
    request: StageCommonsVisualRequest, service: ServiceDependency
) -> VisualDiscoveryAssetView:
    return await service.stage(request)


@router.post(
    "/visual-discovery-assets/{asset_id}/reuse",
    response_model=VisualDiscoveryAssetView,
    status_code=201,
    operation_id="reuseApprovedVisualDiscoveryAsset",
)
async def reuse_approved_visual_discovery_asset(
    asset_id: UUID,
    request: ReuseApprovedVisualRequest,
    service: ServiceDependency,
) -> VisualDiscoveryAssetView:
    return await service.reuse(asset_id, request)


@router.get(
    "/stories/{story_id}/visual-discovery-assets",
    response_model=list[VisualDiscoveryAssetView],
    operation_id="listStoryVisualDiscoveryAssets",
)
async def list_story_visual_discovery_assets(
    story_id: UUID, service: ServiceDependency
) -> list[VisualDiscoveryAssetView]:
    return await service.list(story_id)


@router.post(
    "/visual-discovery-assets/{asset_id}/approve",
    response_model=VisualDiscoveryAssetView,
    operation_id="approveVisualDiscoveryAsset",
)
async def approve_visual_discovery_asset(
    asset_id: UUID, request: VisualDiscoveryReviewRequest, service: ServiceDependency
) -> VisualDiscoveryAssetView:
    return await service.approve(asset_id, request)


@router.post(
    "/visual-discovery-assets/{asset_id}/reject",
    response_model=VisualDiscoveryAssetView,
    operation_id="rejectVisualDiscoveryAsset",
)
async def reject_visual_discovery_asset(
    asset_id: UUID, request: VisualDiscoveryReviewRequest, service: ServiceDependency
) -> VisualDiscoveryAssetView:
    return await service.reject(asset_id, request)


@router.get(
    "/visual-discovery-assets/{asset_id}/content",
    response_class=FileResponse,
    operation_id="getVisualDiscoveryAssetContent",
)
async def visual_discovery_asset_content(
    asset_id: UUID, service: ServiceDependency
) -> FileResponse:
    asset, path = await service.media_path(asset_id)
    return FileResponse(
        path,
        media_type=asset.candidate.mime_type,
        filename=asset.candidate.file_title.removeprefix("File:"),
    )
