from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from god_news.api.dependencies import get_container
from god_news.api.routes import PROBLEM_RESPONSES
from god_news.application.source_transcriptions import SourceMediaTranscriptionService
from god_news.container import AppContainer
from god_news.domain.source_transcription import (
    ReviewSourceTranscriptionRequest,
    SourceMediaTranscription,
    StartSourceTranscriptionRequest,
)
from god_news.errors import ConfigurationError

router = APIRouter(responses=PROBLEM_RESPONSES, tags=["source-transcriptions"])
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _service(container: AppContainer) -> SourceMediaTranscriptionService:
    if container.source_transcriptions is None:
        raise ConfigurationError("Source-media transcription is not configured.")
    return container.source_transcriptions


@router.post(
    "/stories/{story_id}/source-media/{artifact_id}/transcriptions",
    response_model=SourceMediaTranscription,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startSourceMediaTranscription",
)
async def start_source_media_transcription(
    story_id: UUID,
    artifact_id: UUID,
    request: StartSourceTranscriptionRequest,
    container: ContainerDependency,
) -> SourceMediaTranscription:
    return await _service(container).start(story_id, artifact_id, request)


@router.get(
    "/stories/{story_id}/source-media/{artifact_id}/transcriptions",
    response_model=list[SourceMediaTranscription],
    operation_id="listSourceMediaTranscriptions",
)
async def list_source_media_transcriptions(
    story_id: UUID,
    artifact_id: UUID,
    container: ContainerDependency,
) -> list[SourceMediaTranscription]:
    return list(await _service(container).list(story_id, artifact_id))


@router.get(
    "/stories/{story_id}/source-media/{artifact_id}/transcriptions/{transcription_id}",
    response_model=SourceMediaTranscription,
    operation_id="getSourceMediaTranscription",
)
async def get_source_media_transcription(
    story_id: UUID,
    artifact_id: UUID,
    transcription_id: UUID,
    container: ContainerDependency,
) -> SourceMediaTranscription:
    return await _service(container).get(story_id, artifact_id, transcription_id)


@router.post(
    "/stories/{story_id}/source-media/{artifact_id}/transcriptions/"
    "{transcription_id}/review",
    response_model=SourceMediaTranscription,
    operation_id="reviewSourceMediaTranscription",
)
async def review_source_media_transcription(
    story_id: UUID,
    artifact_id: UUID,
    transcription_id: UUID,
    request: ReviewSourceTranscriptionRequest,
    container: ContainerDependency,
) -> SourceMediaTranscription:
    return await _service(container).review(
        story_id,
        artifact_id,
        transcription_id,
        request,
    )


@router.post(
    "/stories/{story_id}/source-media/{artifact_id}/transcriptions/"
    "{transcription_id}/cancel",
    response_model=SourceMediaTranscription,
    operation_id="cancelSourceMediaTranscription",
)
async def cancel_source_media_transcription(
    story_id: UUID,
    artifact_id: UUID,
    transcription_id: UUID,
    container: ContainerDependency,
) -> SourceMediaTranscription:
    return await _service(container).cancel(story_id, artifact_id, transcription_id)
