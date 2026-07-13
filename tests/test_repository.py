from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from god_news.domain.enums import SpeechEmotion, StoryStatus
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


@pytest.mark.asyncio
async def test_sql_repository_hides_archived_stories_from_the_default_list(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'archive.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    try:
        original = await repository.create(make_story())
        archived = await repository.save(
            transition_story(original, StoryStatus.ARCHIVED),
            expected_version=original.version,
            transition_reason="story archived",
        )

        assert (await repository.get(original.story_id)).status is StoryStatus.ARCHIVED
        assert await repository.list() == []
        assert [story.story_id for story in await repository.list(status=StoryStatus.ARCHIVED)] == [
            original.story_id
        ]
        assert [story.story_id for story in await repository.list(include_archived=True)] == [
            original.story_id
        ]
        transitions = await repository.list_transitions(original.story_id)
        assert (transitions[-1].from_status, transitions[-1].to_status) == (
            StoryStatus.FETCHED,
            StoryStatus.ARCHIVED,
        )
        assert archived.version == original.version + 1
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_sqlite_migrates_legacy_failed_tts_retry_to_manual_gate(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'legacy-tts.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    try:
        original = await repository.create(make_story())
        translation, script, _ = make_artifacts()
        # Simulate the legacy failure shape directly: old code could leave
        # PENDING_SECOND_REVIEW without audio after a failed resynthesis.
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE stories SET status = :status, translation_json = :translation, "
                    "script_json = :script, audio_json = NULL, version = :version "
                    "WHERE story_id = :story_id"
                ),
                {
                    "status": StoryStatus.PENDING_SECOND_REVIEW.value,
                    "translation": translation.model_dump_json(),
                    "script": script.model_dump_json(),
                    "version": 7,
                    "story_id": str(original.story_id),
                },
            )

        await database.create_schema()
        migrated = await repository.get(original.story_id)

        assert migrated.status is StoryStatus.PENDING_TTS
        assert migrated.audio is None
        assert migrated.script == script
        assert migrated.version == 8
        transitions = await repository.list_transitions(original.story_id)
        assert (transitions[-1].from_status, transitions[-1].to_status) == (
            StoryStatus.PENDING_SECOND_REVIEW,
            StoryStatus.PENDING_TTS,
        )
        assert "legacy failed TTS" in transitions[-1].reason

        await database.create_schema()
        assert (await repository.get(original.story_id)).version == 8
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_sqlite_migrates_legacy_free_form_story_emotions_with_audit(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'legacy-emotions.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    try:
        original = await repository.create(make_story())
        translation, script, audio = make_artifacts()
        preferences_payload = original.preferences.model_dump(mode="json")
        preferences_payload["emotion"] = "calm"
        script_payload = script.model_dump(mode="json")
        script_payload["segments"][0]["emotion"] = "serious"
        audio_payload = audio.model_dump(mode="json")
        audio_payload["synthesis"]["segment_provenance"] = [
            {
                "segment_id": str(script.segments[0].segment_id),
                "speaker_id": "narrator",
                "emotion": "melancholy",
                "reference_audio_sha256": "0" * 64,
                "reference_text_sha256": "0" * 64,
                "gpt_weights_sha256": "0" * 64,
                "sovits_weights_sha256": "0" * 64,
                "model_identity": "fixture-v1",
                "prompt_language": "en",
            }
        ]
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE stories SET status = :status, preferences_json = :preferences, "
                    "translation_json = :translation, script_json = :script, audio_json = :audio "
                    "WHERE story_id = :story_id"
                ),
                {
                    "status": StoryStatus.DONE.value,
                    "preferences": json.dumps(preferences_payload),
                    "translation": translation.model_dump_json(),
                    "script": json.dumps(script_payload),
                    "audio": json.dumps(audio_payload),
                    "story_id": str(original.story_id),
                },
            )

        await database.create_schema()
        migrated = await repository.get(original.story_id)

        assert migrated.version == original.version + 1
        assert migrated.preferences.emotion is SpeechEmotion.HAPPINESS
        assert migrated.script is not None
        assert migrated.script.segments[0].emotion is SpeechEmotion.HAPPINESS
        assert migrated.audio is not None
        assert migrated.audio.synthesis.segment_provenance[0].emotion is SpeechEmotion.HAPPINESS
        transitions = await repository.list_transitions(original.story_id)
        assert transitions[-1].from_status is StoryStatus.DONE
        assert transitions[-1].to_status is StoryStatus.DONE
        assert "calm" in transitions[-1].reason
        assert "serious" in transitions[-1].reason
        assert "melancholy" in transitions[-1].reason
    finally:
        await database.aclose()
