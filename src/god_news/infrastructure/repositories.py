from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.domain.deduplication import StoryIdentity, story_identity
from god_news.domain.enums import ContentCategory, ReviewDecision, ReviewStage, StoryStatus
from god_news.domain.fsm import validate_story_invariants, validate_transition_evidence
from god_news.domain.models import (
    AudioBundle,
    ClassificationMetrics,
    PipelineFailure,
    ReviewRecord,
    ScriptDocument,
    ScriptPreferences,
    SourceSnapshot,
    StateTransition,
    Story,
    TranslationResult,
)
from god_news.domain.video import VideoBatch, VideoBatchStatus
from god_news.errors import ConcurrentWriteError, DuplicateStoryError, StoryNotFoundError
from god_news.infrastructure.database import Base
from god_news.infrastructure.video_repository import VideoBatchRow
from god_news.sources.models import NormalizedSourceItem


class StoryRow(Base):
    __tablename__ = "stories"

    story_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_language: Mapped[str] = mapped_column(String(64), nullable=False)
    preferences_json: Mapped[str] = mapped_column(Text, nullable=False)
    translation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_stories_status_updated", "status", "updated_at"),
        Index(
            "ux_stories_canonical_url_sha256",
            "canonical_url_sha256",
            unique=True,
        ),
        Index(
            "ux_stories_source_content_sha256",
            "source_content_sha256",
            unique=True,
        ),
    )


class ReviewRow(Base):
    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("stories.story_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_story_version: Mapped[int] = mapped_column(Integer, nullable=False)
    translation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    script_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransitionRow(Base):
    __tablename__ = "state_transitions"

    transition_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("stories.story_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_or_none(value: BaseModel | None) -> str | None:
    if value is None:
        return None
    return value.model_dump_json()


def _story_values(story: Story, *, version: int) -> dict[str, object]:
    identity = story_identity(story)
    return {
        "trace_id": str(story.trace_id),
        "status": story.status.value,
        "title": story.title,
        "source_json": story.source.model_dump_json(),
        "provenance_json": _json_or_none(story.provenance),
        "canonical_url_sha256": identity.canonical_url_sha256,
        "source_content_sha256": identity.content_sha256,
        "original_text": story.original_text,
        "target_language": story.target_language,
        "preferences_json": story.preferences.model_dump_json(),
        "translation_json": _json_or_none(story.translation),
        "script_json": _json_or_none(story.script),
        "audio_json": _json_or_none(story.audio),
        "last_failure_json": _json_or_none(story.last_failure),
        "version": version,
        "created_at": story.created_at,
        "updated_at": story.updated_at,
    }


def _to_story(row: StoryRow) -> Story:
    return Story(
        story_id=UUID(row.story_id),
        trace_id=UUID(row.trace_id),
        status=StoryStatus(row.status),
        title=row.title,
        source=SourceSnapshot.model_validate_json(row.source_json),
        provenance=(
            NormalizedSourceItem.model_validate_json(row.provenance_json)
            if row.provenance_json
            else None
        ),
        original_text=row.original_text,
        target_language=row.target_language,
        preferences=ScriptPreferences.model_validate_json(row.preferences_json),
        translation=(
            TranslationResult.model_validate_json(row.translation_json)
            if row.translation_json
            else None
        ),
        script=ScriptDocument.model_validate_json(row.script_json) if row.script_json else None,
        audio=AudioBundle.model_validate_json(row.audio_json) if row.audio_json else None,
        last_failure=(
            PipelineFailure.model_validate_json(row.last_failure_json)
            if row.last_failure_json
            else None
        ),
        version=row.version,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


class SqlAlchemyStoryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, story: Story) -> Story:
        validate_story_invariants(story)
        row = StoryRow(story_id=str(story.story_id), **_story_values(story, version=story.version))
        async with self._sessions() as session:
            try:
                async with session.begin():
                    duplicate = await self._find_duplicate(session, story_identity(story))
                    if duplicate is not None:
                        raise DuplicateStoryError(*duplicate)
                    session.add(row)
            except IntegrityError as exc:
                async with self._sessions() as lookup_session:
                    duplicate = await self._find_duplicate(
                        lookup_session,
                        story_identity(story),
                    )
                if duplicate is not None:
                    raise DuplicateStoryError(*duplicate) from exc
                raise ConcurrentWriteError(story.story_id) from exc
        return story

    @staticmethod
    async def _find_duplicate(
        session: AsyncSession,
        identity: StoryIdentity,
    ) -> tuple[UUID, str] | None:
        if identity.canonical_url_sha256 is not None:
            story_id = await session.scalar(
                select(StoryRow.story_id)
                .where(StoryRow.canonical_url_sha256 == identity.canonical_url_sha256)
                .limit(1)
            )
            if story_id is not None:
                return UUID(story_id), "canonical URL"
        story_id = await session.scalar(
            select(StoryRow.story_id)
            .where(StoryRow.source_content_sha256 == identity.content_sha256)
            .limit(1)
        )
        if story_id is not None:
            return UUID(story_id), "normalized content"
        return None

    async def get(self, story_id: UUID) -> Story:
        async with self._sessions() as session:
            row = await session.get(StoryRow, str(story_id))
        if row is None:
            raise StoryNotFoundError(story_id)
        return _to_story(row)

    async def list(
        self,
        *,
        status: StoryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> Sequence[Story]:
        statement = (
            select(StoryRow).order_by(StoryRow.updated_at.desc()).limit(limit).offset(offset)
        )
        if status is not None:
            statement = statement.where(StoryRow.status == status.value)
        elif not include_archived:
            statement = statement.where(StoryRow.status != StoryStatus.ARCHIVED.value)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_story(row) for row in rows]

    async def save(
        self,
        story: Story,
        *,
        expected_version: int,
        transition_reason: str | None = None,
        review: ReviewRecord | None = None,
    ) -> Story:
        validate_story_invariants(story)
        next_version = expected_version + 1
        async with self._sessions() as session:
            async with session.begin():
                previous = await session.get(StoryRow, str(story.story_id))
                if previous is None:
                    raise StoryNotFoundError(story.story_id)
                previous_status = StoryStatus(previous.status)
                if previous_status is not story.status:
                    validate_transition_evidence(previous_status, story.status, story, review)
                result = await session.execute(
                    update(StoryRow)
                    .where(
                        StoryRow.story_id == str(story.story_id),
                        StoryRow.version == expected_version,
                    )
                    .values(**_story_values(story, version=next_version))
                )
                cursor_result = cast(CursorResult[Any], result)
                if cursor_result.rowcount != 1:
                    raise ConcurrentWriteError(story.story_id)
                if previous_status is not story.status:
                    transition = StateTransition(
                        story_id=story.story_id,
                        from_status=previous_status,
                        to_status=story.status,
                        reason=transition_reason or "pipeline transition",
                    )
                    session.add(
                        TransitionRow(
                            transition_id=str(transition.transition_id),
                            story_id=str(transition.story_id),
                            from_status=transition.from_status.value,
                            to_status=transition.to_status.value,
                            reason=transition.reason,
                            occurred_at=transition.occurred_at,
                        )
                    )
                if review is not None:
                    session.add(
                        ReviewRow(
                            review_id=str(review.review_id),
                            story_id=str(review.story_id),
                            stage=review.stage.value,
                            decision=review.decision.value,
                            reviewer_id=review.reviewer_id,
                            note=review.note,
                            reviewed_story_version=review.reviewed_story_version,
                            translation_sha256=review.translation_sha256,
                            script_revision=review.script_revision,
                            audio_sha256=review.audio_sha256,
                            request_sha256=review.request_sha256,
                            ai_category=(review.ai_category.value if review.ai_category else None),
                            human_category=(
                                review.human_category.value if review.human_category else None
                            ),
                            classification_accepted=review.classification_accepted,
                            created_at=review.created_at,
                        )
                    )
        return story.model_copy(update={"version": next_version})

    async def add_review(self, review: ReviewRecord) -> None:
        row = ReviewRow(
            review_id=str(review.review_id),
            story_id=str(review.story_id),
            stage=review.stage.value,
            decision=review.decision.value,
            reviewer_id=review.reviewer_id,
            note=review.note,
            reviewed_story_version=review.reviewed_story_version,
            translation_sha256=review.translation_sha256,
            script_revision=review.script_revision,
            audio_sha256=review.audio_sha256,
            request_sha256=review.request_sha256,
            ai_category=review.ai_category.value if review.ai_category else None,
            human_category=review.human_category.value if review.human_category else None,
            classification_accepted=review.classification_accepted,
            created_at=review.created_at,
        )
        async with self._sessions() as session:
            async with session.begin():
                session.add(row)

    async def list_reviews(self, story_id: UUID) -> Sequence[ReviewRecord]:
        statement = (
            select(ReviewRow)
            .where(ReviewRow.story_id == str(story_id))
            .order_by(ReviewRow.created_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [
            ReviewRecord(
                review_id=UUID(row.review_id),
                story_id=UUID(row.story_id),
                stage=ReviewStage(row.stage),
                decision=ReviewDecision(row.decision),
                reviewer_id=row.reviewer_id,
                note=row.note,
                reviewed_story_version=row.reviewed_story_version,
                translation_sha256=row.translation_sha256,
                script_revision=row.script_revision,
                audio_sha256=row.audio_sha256,
                request_sha256=row.request_sha256,
                ai_category=ContentCategory(row.ai_category) if row.ai_category else None,
                human_category=(
                    ContentCategory(row.human_category) if row.human_category else None
                ),
                classification_accepted=row.classification_accepted,
                created_at=_aware(row.created_at),
            )
            for row in rows
        ]

    async def get_review(self, review_id: UUID) -> ReviewRecord | None:
        async with self._sessions() as session:
            row = await session.get(ReviewRow, str(review_id))
        if row is None:
            return None
        return ReviewRecord(
            review_id=UUID(row.review_id),
            story_id=UUID(row.story_id),
            stage=ReviewStage(row.stage),
            decision=ReviewDecision(row.decision),
            reviewer_id=row.reviewer_id,
            note=row.note,
            reviewed_story_version=row.reviewed_story_version,
            translation_sha256=row.translation_sha256,
            script_revision=row.script_revision,
            audio_sha256=row.audio_sha256,
            request_sha256=row.request_sha256,
            ai_category=ContentCategory(row.ai_category) if row.ai_category else None,
            human_category=(ContentCategory(row.human_category) if row.human_category else None),
            classification_accepted=row.classification_accepted,
            created_at=_aware(row.created_at),
        )

    async def list_transitions(self, story_id: UUID) -> Sequence[StateTransition]:
        statement = (
            select(TransitionRow)
            .where(TransitionRow.story_id == str(story_id))
            .order_by(TransitionRow.occurred_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [
            StateTransition(
                transition_id=UUID(row.transition_id),
                story_id=UUID(row.story_id),
                from_status=StoryStatus(row.from_status),
                to_status=StoryStatus(row.to_status),
                reason=row.reason,
                occurred_at=_aware(row.occurred_at),
            )
            for row in rows
        ]

    async def classification_metrics(self) -> ClassificationMetrics:
        statement = select(
            func.count(ReviewRow.review_id),
            func.sum(
                func.coalesce(
                    ReviewRow.classification_accepted.cast(Integer),
                    0,
                )
            ),
        ).where(ReviewRow.classification_accepted.is_not(None))
        async with self._sessions() as session:
            reviewed, accepted = (await session.execute(statement)).one()
        reviewed_count = int(reviewed or 0)
        accepted_count = int(accepted or 0)
        return ClassificationMetrics(
            reviewed_count=reviewed_count,
            accepted_count=accepted_count,
            accuracy=(accepted_count / reviewed_count if reviewed_count else None),
        )

    async def healthcheck(self) -> None:
        async with self._sessions() as session:
            await session.execute(select(1))


class SqlAlchemyLiveScriptRoleUsageGuard:
    """Read-only production-side adapter for safe role-profile mutation.

    The role application service owns the policy for changing a voice contract.
    This adapter only identifies scripts that can still be rendered and hence
    must keep resolving their recorded ``speaker_id``. Parsing each persisted
    script, rather than using a JSON substring query, keeps the decision exact
    across SQLite versions and intentionally fails closed when old/corrupt data
    cannot be understood by the current script contract.
    """

    _LIVE_SCRIPT_STATUSES = (
        StoryStatus.SCRIPT_READY,
        StoryStatus.PENDING_TTS,
        StoryStatus.PROCESSING_TTS,
        StoryStatus.PENDING_SECOND_REVIEW,
    )
    _LIVE_BATCH_STATUSES = (
        VideoBatchStatus.PENDING_NARRATION_REVIEW,
        VideoBatchStatus.PENDING_BATCH_TTS,
        VideoBatchStatus.PROCESSING_BATCH_TTS,
        VideoBatchStatus.PENDING_TIMELINE_REVIEW,
        VideoBatchStatus.READY_TO_RENDER,
        VideoBatchStatus.RENDERING,
    )

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def has_live_script_reference(self, speaker_id: str) -> bool:
        statement = select(StoryRow.script_json).where(
            StoryRow.status.in_(tuple(status.value for status in self._LIVE_SCRIPT_STATUSES)),
            StoryRow.script_json.is_not(None),
        )
        batch_statement = select(VideoBatchRow.batch_json).where(
            VideoBatchRow.status.in_(
                tuple(status.value for status in self._LIVE_BATCH_STATUSES)
            )
        )
        async with self._sessions() as session:
            serialized_scripts = (await session.scalars(statement)).all()
            serialized_batches = (await session.scalars(batch_statement)).all()
        for serialized in serialized_scripts:
            if serialized is None:
                continue
            script = ScriptDocument.model_validate_json(serialized)
            if any(segment.speaker_id == speaker_id for segment in script.segments):
                return True
        for serialized in serialized_batches:
            batch = VideoBatch.model_validate_json(serialized)
            if any(
                segment.speaker_id == speaker_id
                for segment in batch.narration.script.segments
            ):
                return True
        return False
