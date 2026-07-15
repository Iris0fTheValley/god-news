from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.source_media import SourceMediaRepository, StoredSourceMediaArtifact
from god_news.infrastructure.database import Base


class SourceMediaArtifactRow(Base):
    __tablename__ = "source_media_artifacts"
    __table_args__ = (
        UniqueConstraint("story_id", "media_index", name="uq_source_media_story_index"),
    )

    artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    media_index: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_json: Mapped[str] = mapped_column(Text, nullable=False)


class SqlAlchemySourceMediaRepository(SourceMediaRepository):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        storage_root: Path,
    ) -> None:
        self._sessions = sessions
        self._storage_root = storage_root.expanduser().resolve(strict=False)

    async def list_for_story(self, story_id: UUID) -> Sequence[StoredSourceMediaArtifact]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceMediaArtifactRow)
                    .where(SourceMediaArtifactRow.story_id == str(story_id))
                    .order_by(SourceMediaArtifactRow.media_index)
                )
            ).all()
        return [StoredSourceMediaArtifact.model_validate_json(row.artifact_json) for row in rows]

    async def get_by_index(
        self,
        story_id: UUID,
        media_index: int,
    ) -> StoredSourceMediaArtifact | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SourceMediaArtifactRow).where(
                    SourceMediaArtifactRow.story_id == str(story_id),
                    SourceMediaArtifactRow.media_index == media_index,
                )
            )
        return (
            StoredSourceMediaArtifact.model_validate_json(row.artifact_json)
            if row is not None
            else None
        )

    async def create(self, artifact: StoredSourceMediaArtifact) -> StoredSourceMediaArtifact:
        row = SourceMediaArtifactRow(
            artifact_id=str(artifact.artifact_id),
            story_id=str(artifact.story_id),
            media_index=artifact.media_index,
            artifact_json=artifact.model_dump_json(),
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError:
            existing = await self.get_by_index(artifact.story_id, artifact.media_index)
            if existing is not None:
                return existing
            raise
        return artifact

    async def protected_asset_paths(self) -> Sequence[Path]:
        async with self._sessions() as session:
            payloads = (
                await session.scalars(select(SourceMediaArtifactRow.artifact_json))
            ).all()
        paths: list[Path] = []
        for payload in payloads:
            try:
                artifact = StoredSourceMediaArtifact.model_validate_json(payload)
                candidate = self._storage_root / artifact.storage_key
                resolved = candidate.resolve(strict=False)
            except (OSError, ValueError):
                continue
            if resolved.is_relative_to(self._storage_root):
                paths.append(resolved)
        return paths
