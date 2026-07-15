from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Integer, String, Text, UniqueConstraint, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.source_transcription import (
    SourceMediaTranscription,
    SourceTranscriptionFailure,
    SourceTranscriptionRepository,
    SourceTranscriptionStatus,
)
from god_news.errors import (
    ConcurrentSourceTranscriptionWriteError,
    SourceTranscriptionNotFoundError,
)
from god_news.infrastructure.database import Base


class SourceMediaTranscriptionRow(Base):
    __tablename__ = "source_media_transcriptions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "artifact_sha256",
            "model_identity",
            "source_language_hint_key",
            "target_caption_language",
            name="uq_source_transcription_equivalent",
        ),
    )

    transcription_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    source_language_hint_key: Mapped[str] = mapped_column(String(35), nullable=False)
    target_caption_language: Mapped[str] = mapped_column(String(35), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    transcription_json: Mapped[str] = mapped_column(Text, nullable=False)


class SqlAlchemySourceTranscriptionRepository(SourceTranscriptionRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_or_get(
        self,
        transcription: SourceMediaTranscription,
    ) -> SourceMediaTranscription:
        row = self._row(transcription)
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError:
            existing = await self.find_equivalent(
                artifact_id=transcription.artifact_id,
                artifact_sha256=transcription.artifact_sha256,
                model_identity=transcription.model_identity,
                source_language_hint=transcription.source_language_hint,
                target_caption_language=transcription.target_caption_language,
            )
            if existing is not None:
                return existing
            raise
        return transcription

    async def find_equivalent(
        self,
        *,
        artifact_id: UUID,
        artifact_sha256: str,
        model_identity: str,
        source_language_hint: str | None,
        target_caption_language: str,
    ) -> SourceMediaTranscription | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SourceMediaTranscriptionRow).where(
                    SourceMediaTranscriptionRow.artifact_id == str(artifact_id),
                    SourceMediaTranscriptionRow.artifact_sha256 == artifact_sha256,
                    SourceMediaTranscriptionRow.model_identity == model_identity,
                    SourceMediaTranscriptionRow.source_language_hint_key
                    == (source_language_hint or ""),
                    SourceMediaTranscriptionRow.target_caption_language == target_caption_language,
                )
            )
        return (
            SourceMediaTranscription.model_validate_json(row.transcription_json)
            if row is not None
            else None
        )

    async def get(self, transcription_id: UUID) -> SourceMediaTranscription:
        async with self._sessions() as session:
            row = await session.get(SourceMediaTranscriptionRow, str(transcription_id))
        if row is None:
            raise SourceTranscriptionNotFoundError(transcription_id)
        return SourceMediaTranscription.model_validate_json(row.transcription_json)

    async def list_for_artifact(self, artifact_id: UUID) -> Sequence[SourceMediaTranscription]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceMediaTranscriptionRow)
                    .where(SourceMediaTranscriptionRow.artifact_id == str(artifact_id))
                    .order_by(SourceMediaTranscriptionRow.transcription_id)
                )
            ).all()
        items = [
            SourceMediaTranscription.model_validate_json(row.transcription_json) for row in rows
        ]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    async def save(
        self,
        transcription: SourceMediaTranscription,
        *,
        expected_version: int,
    ) -> SourceMediaTranscription:
        if transcription.version != expected_version + 1:
            raise ValueError("saved transcription version must increment exactly once")
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(SourceMediaTranscriptionRow)
                .where(
                    SourceMediaTranscriptionRow.transcription_id
                    == str(transcription.transcription_id),
                    SourceMediaTranscriptionRow.version == expected_version,
                )
                .values(
                    status=transcription.status.value,
                    version=transcription.version,
                    transcription_json=transcription.model_dump_json(),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise ConcurrentSourceTranscriptionWriteError(transcription.story_id)
        return transcription

    async def recover_interrupted(self) -> int:
        active = await self._list_by_status(
            {SourceTranscriptionStatus.QUEUED, SourceTranscriptionStatus.PROCESSING}
        )
        recovered = 0
        for item in active:
            failure = SourceTranscriptionFailure(
                code="service_restarted",
                message="The ASR task stopped when the service restarted; retry explicitly.",
                retryable=True,
            )
            failed = item.evolve(
                status=SourceTranscriptionStatus.FAILED,
                failures=[*item.failures, failure],
                version=item.version + 1,
                updated_at=datetime.now(UTC),
            )
            try:
                await self.save(failed, expected_version=item.version)
            except ConcurrentSourceTranscriptionWriteError:
                continue
            recovered += 1
        return recovered

    async def _list_by_status(
        self,
        statuses: set[SourceTranscriptionStatus],
    ) -> list[SourceMediaTranscription]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceMediaTranscriptionRow).where(
                        SourceMediaTranscriptionRow.status.in_(item.value for item in statuses)
                    )
                )
            ).all()
        return [
            SourceMediaTranscription.model_validate_json(row.transcription_json) for row in rows
        ]

    @staticmethod
    def _row(transcription: SourceMediaTranscription) -> SourceMediaTranscriptionRow:
        return SourceMediaTranscriptionRow(
            transcription_id=str(transcription.transcription_id),
            story_id=str(transcription.story_id),
            artifact_id=str(transcription.artifact_id),
            artifact_sha256=transcription.artifact_sha256,
            model_identity=transcription.model_identity,
            source_language_hint_key=transcription.source_language_hint or "",
            target_caption_language=transcription.target_caption_language,
            status=transcription.status.value,
            version=transcription.version,
            transcription_json=transcription.model_dump_json(),
        )
