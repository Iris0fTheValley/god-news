from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.application.media_catalog import MediaCatalogService
from god_news.container import AppContainer
from god_news.domain.media_catalog import (
    ChangeMediaLifecycleRequest,
    MediaCatalogEntry,
    MediaCatalogKind,
    MediaCatalogLifecycle,
    MediaCatalogPage,
    MediaCatalogSourceKind,
)
from god_news.errors import ConfigurationError

router = APIRouter(
    prefix="/media-assets",
    tags=["media-catalog"],
    responses={
        404: {"model": ProblemDetail},
        409: {"model": ProblemDetail},
        422: {"model": ProblemDetail},
        503: {"model": ProblemDetail},
    },
)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _service(container: ContainerDependency) -> MediaCatalogService:
    if container.media_catalog is None:
        raise ConfigurationError("Media catalog is not configured.")
    return container.media_catalog


ServiceDependency = Annotated[MediaCatalogService, Depends(_service)]


@router.get("", response_model=MediaCatalogPage, operation_id="listMediaCatalogAssets")
async def list_media_catalog_assets(
    service: ServiceDependency,
    search: str | None = None,
    source_kind: MediaCatalogSourceKind | None = None,
    media_kind: MediaCatalogKind | None = None,
    lifecycle: MediaCatalogLifecycle | None = None,
    story_id: UUID | None = None,
    publish_eligible: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MediaCatalogPage:
    return await service.list(
        search=search,
        source_kind=source_kind,
        media_kind=media_kind,
        lifecycle=lifecycle,
        story_id=story_id,
        publish_eligible=publish_eligible,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{catalog_id}",
    response_model=MediaCatalogEntry,
    operation_id="getMediaCatalogAsset",
)
async def get_media_catalog_asset(
    catalog_id: str,
    service: ServiceDependency,
) -> MediaCatalogEntry:
    return await service.get(catalog_id)


@router.get(
    "/{catalog_id}/content",
    response_class=FileResponse,
    operation_id="getMediaCatalogAssetContent",
)
async def get_media_catalog_asset_content(
    catalog_id: str,
    service: ServiceDependency,
) -> FileResponse:
    mime_type, filename, path = await service.media_path(catalog_id)
    return FileResponse(path, media_type=mime_type, filename=filename)


@router.post(
    "/{catalog_id}/archive",
    response_model=MediaCatalogEntry,
    operation_id="archiveMediaCatalogAsset",
)
async def archive_media_catalog_asset(
    catalog_id: str,
    request: ChangeMediaLifecycleRequest,
    service: ServiceDependency,
) -> MediaCatalogEntry:
    return await service.archive(catalog_id, request)


@router.post(
    "/{catalog_id}/restore",
    response_model=MediaCatalogEntry,
    operation_id="restoreMediaCatalogAsset",
)
async def restore_media_catalog_asset(
    catalog_id: str,
    request: ChangeMediaLifecycleRequest,
    service: ServiceDependency,
) -> MediaCatalogEntry:
    return await service.restore(catalog_id, request)
