from __future__ import annotations

from pathlib import Path

import pytest

from god_news.domain.enums import StoryStatus
from god_news.domain.fsm import transition_story
from god_news.errors import ConcurrentWriteError, InvalidTransitionError
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository

from .test_fsm import make_artifacts, make_story


@pytest.mark.asyncio
async def test_sql_repository_uses_optimistic_concurrency_and_audit(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'repo.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    try:
        original = await repository.create(make_story())
        translation, _, _ = make_artifacts()
        translated = await repository.save(
            transition_story(
                original,
                StoryStatus.TRANSLATED,
                translation=translation,
            ),
            expected_version=original.version,
            transition_reason="test transition",
        )
        assert translated.version == original.version + 1

        with pytest.raises(ConcurrentWriteError):
            await repository.save(
                transition_story(
                    original,
                    StoryStatus.TRANSLATED,
                    translation=translation,
                ),
                expected_version=original.version,
            )
        transitions = await repository.list_transitions(original.story_id)
        assert len(transitions) == 1
        assert transitions[0].reason == "test transition"

        pending = await repository.save(
            transition_story(translated, StoryStatus.PENDING_FIRST_REVIEW),
            expected_version=translated.version,
        )
        with pytest.raises(InvalidTransitionError):
            await repository.save(
                transition_story(pending, StoryStatus.PROCESSING_SCRIPT),
                expected_version=pending.version,
            )

        _, script, audio = make_artifacts()
        illegal_done = pending.model_copy(
            update={
                "status": StoryStatus.DONE,
                "translation": translation,
                "script": script,
                "audio": audio,
            }
        )
        with pytest.raises(InvalidTransitionError, match="cannot transition"):
            await repository.save(
                illegal_done,
                expected_version=pending.version,
            )
    finally:
        await database.aclose()
