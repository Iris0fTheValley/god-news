from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from god_news.domain.enums import StoryStatus
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import (
    SqlAlchemyLiveScriptRoleUsageGuard,
    SqlAlchemyStoryRepository,
)

from .test_fsm import make_artifacts, make_story


@pytest.mark.asyncio
async def test_live_script_role_usage_guard_only_locks_renderable_story_states(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'roles-in-use.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    guard = SqlAlchemyLiveScriptRoleUsageGuard(database.sessions)
    try:
        story = await repository.create(make_story())
        translation, script, _ = make_artifacts()
        locked_script = script.model_copy(
            update={
                "segments": [
                    script.segments[0].model_copy(update={"speaker_id": "locked-narrator"})
                ]
            }
        )
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE stories SET status = :status, translation_json = :translation, "
                    "script_json = :script WHERE story_id = :story_id"
                ),
                {
                    "status": StoryStatus.SCRIPT_READY.value,
                    "translation": translation.model_dump_json(),
                    "script": locked_script.model_dump_json(),
                    "story_id": str(story.story_id),
                },
            )

        assert await guard.has_live_script_reference("locked-narrator")
        assert not await guard.has_live_script_reference("unreferenced-narrator")

        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE stories SET status = :status WHERE story_id = :story_id"),
                {"status": StoryStatus.DONE.value, "story_id": str(story.story_id)},
            )
        assert not await guard.has_live_script_reference("locked-narrator")
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_live_script_role_usage_guard_rejects_unreadable_live_script(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'roles-corrupt.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    guard = SqlAlchemyLiveScriptRoleUsageGuard(database.sessions)
    try:
        story = await repository.create(make_story())
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE stories SET status = :status, script_json = :script "
                    "WHERE story_id = :story_id"
                ),
                {
                    "status": StoryStatus.SCRIPT_READY.value,
                    "script": '{"malformed": true}',
                    "story_id": str(story.story_id),
                },
            )

        with pytest.raises(ValidationError):
            await guard.has_live_script_reference("locked-narrator")
    finally:
        await database.aclose()
