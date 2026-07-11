from __future__ import annotations

import pytest

from god_news.domain.enums import ContentCategory, StoryStatus
from god_news.domain.fsm import all_transitions, transition_story
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    EditorialScreening,
    FetchedDocument,
    ScriptDocument,
    ScriptPreferences,
    ScriptSegment,
    Story,
    SynthesisMetadata,
    TextSource,
    TranslationResult,
)
from god_news.errors import InvalidTransitionError

EXPECTED = (
    (StoryStatus.FETCHED, StoryStatus.TRANSLATED),
    (StoryStatus.TRANSLATED, StoryStatus.PENDING_FIRST_REVIEW),
    (StoryStatus.PENDING_FIRST_REVIEW, StoryStatus.PROCESSING_SCRIPT),
    (StoryStatus.PROCESSING_SCRIPT, StoryStatus.SCRIPT_READY),
    (StoryStatus.SCRIPT_READY, StoryStatus.PENDING_SECOND_REVIEW),
    (StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.DONE),
)


def make_story() -> Story:
    fetched = FetchedDocument.from_text(
        TextSource(text="A factual source article.", title="Fixture", language="en")
    )
    return Story(
        status=StoryStatus.FETCHED,
        source=fetched.source,
        original_text=fetched.content,
        target_language="zh-CN",
        preferences=ScriptPreferences(
            style="accurate",
            target_duration_seconds=60,
            speaker_id="narrator",
        ),
    )


def make_artifacts() -> tuple[TranslationResult, ScriptDocument, AudioBundle]:
    translation = TranslationResult(
        source_language="en",
        target_language="zh-CN",
        translated_text="测试译文",
        summary="测试摘要",
        key_points=["测试要点"],
        screening=EditorialScreening(
            model_category=ContentCategory.KINDNESS,
            category=ContentCategory.KINDNESS,
            model_candidate_recommendation=True,
            candidate_recommendation=True,
            confidence=0.9,
            rationale="Fixture classification.",
        ),
    )
    segment = ScriptSegment(
        sequence=0,
        text="测试旁白",
        speaker_id="narrator",
        emotion="neutral",
        speed=1.0,
        pitch=0.0,
    )
    script = ScriptDocument(
        title="测试脚本",
        language="zh-CN",
        segments=[segment],
    )
    digest = "0" * 64
    audio = AudioBundle(
        revision=1,
        provider="fixture",
        model_identity="fixture-v1",
        synthesis=SynthesisMetadata(
            seed=0,
            reference_audio_sha256=digest,
            runtime_config_sha256=digest,
            gpt_weights_sha256=digest,
            sovits_weights_sha256=digest,
            prompt_language="en",
            text_language="zh",
        ),
        clips=[
            AudioClip(
                segment_id=segment.segment_id,
                path="fixture.wav",
                duration_ms=1000,
                sample_rate_hz=16000,
                channels=1,
                sha256=digest,
            )
        ],
    )
    return translation, script, audio


def test_fsm_contains_only_the_fixed_linear_transitions() -> None:
    assert set(all_transitions()) == set(EXPECTED)
    assert len(StoryStatus) == 7


def test_fsm_rejects_skipping_a_review_gate() -> None:
    with pytest.raises(InvalidTransitionError):
        transition_story(make_story(), StoryStatus.SCRIPT_READY)


def test_fsm_walks_the_complete_path() -> None:
    story = make_story()
    translation, script, audio = make_artifacts()
    story = transition_story(story, StoryStatus.TRANSLATED, translation=translation)
    story = transition_story(story, StoryStatus.PENDING_FIRST_REVIEW)
    story = transition_story(story, StoryStatus.PROCESSING_SCRIPT)
    story = transition_story(story, StoryStatus.SCRIPT_READY, script=script)
    story = transition_story(story, StoryStatus.PENDING_SECOND_REVIEW, audio=audio)
    story = transition_story(story, StoryStatus.DONE)
    assert story.status is StoryStatus.DONE
