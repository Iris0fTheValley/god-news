from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from god_news.api.dependencies import get_container
from god_news.api.routes import PROBLEM_RESPONSES
from god_news.application.source_media import SourceMediaService
from god_news.container import AppContainer
from god_news.domain.source_media import AcquireSourceMediaRequest, SourceMediaArtifact
from god_news.errors import ConfigurationError

router = APIRouter(responses=PROBLEM_RESPONSES)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _service(container: AppContainer) -> SourceMediaService:
    if container.source_media is None:
        raise ConfigurationError(
            "Source media acquisition is unavailable because ffprobe is missing."
        )
    return container.source_media


@router.get(
    "/stories/{story_id}/source-media",
    response_model=list[SourceMediaArtifact],
    operation_id="listSourceMediaArtifacts",
    tags=["source-media"],
)
async def list_source_media(
    story_id: UUID,
    container: ContainerDependency,
) -> list[SourceMediaArtifact]:
    return await _service(container).list(story_id)


@router.post(
    "/stories/{story_id}/source-media/acquire",
    response_model=SourceMediaArtifact,
    status_code=201,
    operation_id="acquireSourceMedia",
    tags=["source-media"],
)
async def acquire_source_media(
    story_id: UUID,
    request: AcquireSourceMediaRequest,
    container: ContainerDependency,
) -> SourceMediaArtifact:
    return await _service(container).acquire(story_id, request)


@router.get(
    "/stories/{story_id}/source-media/{artifact_id}/content",
    response_class=FileResponse,
    operation_id="getSourceMediaContent",
    tags=["source-media"],
)
async def source_media_content(
    story_id: UUID,
    artifact_id: UUID,
    container: ContainerDependency,
) -> FileResponse:
    artifact, path = await _service(container).media_path(story_id, artifact_id)
    return FileResponse(
        path,
        media_type=artifact.content_type,
        filename=artifact.filename,
    )
