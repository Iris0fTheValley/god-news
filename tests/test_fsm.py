from __future__ import annotations

import pytest
from pydantic import ValidationError

from god_news.domain.enums import ContentCategory, SpeechEmotion, StoryStatus
from god_news.domain.fsm import all_transitions, transition_story
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    EditorialScreening,
    FetchedDocument,
    PipelineFailure,
    ScriptDocument,
    ScriptPreferences,
    ScriptSegment,
    SegmentSynthesisProvenance,
    Story,
    SynthesisMetadata,
    TextSource,
    TranslationResult,
)
from god_news.errors import InvalidTransitionError

EXPECTED = (
    (StoryStatus.FETCHED, StoryStatus.TRANSLATED),
    (StoryStatus.FETCHED, StoryStatus.ARCHIVED),
    (StoryStatus.TRANSLATED, StoryStatus.PENDING_FIRST_REVIEW),
    (StoryStatus.TRANSLATED, StoryStatus.ARCHIVED),
    (StoryStatus.PENDING_FIRST_REVIEW, StoryStatus.PROCESSING_SCRIPT),
    (StoryStatus.PENDING_FIRST_REVIEW, StoryStatus.ARCHIVED),
    (StoryStatus.PROCESSING_SCRIPT, StoryStatus.SCRIPT_READY),
    (StoryStatus.PROCESSING_SCRIPT, StoryStatus.ARCHIVED),
    (StoryStatus.SCRIPT_READY, StoryStatus.PENDING_TTS),
    (StoryStatus.SCRIPT_READY, StoryStatus.ARCHIVED),
    (StoryStatus.PENDING_TTS, StoryStatus.PROCESSING_TTS),
    (StoryStatus.PENDING_TTS, StoryStatus.ARCHIVED),
    (StoryStatus.PROCESSING_TTS, StoryStatus.PENDING_TTS),
    (StoryStatus.PROCESSING_TTS, StoryStatus.PENDING_SECOND_REVIEW),
    (StoryStatus.PROCESSING_TTS, StoryStatus.ARCHIVED),
    (StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.SCRIPT_READY),
    (StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.DONE),
    (StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.ARCHIVED),
    (StoryStatus.DONE, StoryStatus.PENDING_SECOND_REVIEW),
    (StoryStatus.DONE, StoryStatus.ARCHIVED),
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


def test_fsm_contains_the_pipeline_reopen_and_soft_archive_transitions() -> None:
    assert set(all_transitions()) == set(EXPECTED)
    assert len(StoryStatus) == 10


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
    story = transition_story(story, StoryStatus.PENDING_TTS)
    story = transition_story(story, StoryStatus.PROCESSING_TTS)
    story = transition_story(story, StoryStatus.PENDING_SECOND_REVIEW, audio=audio)
    story = transition_story(story, StoryStatus.DONE)
    assert story.status is StoryStatus.DONE


def test_fsm_reopens_done_only_and_archives_from_every_live_state() -> None:
    story = make_story()
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED

    translation, script, audio = make_artifacts()
    story = transition_story(story, StoryStatus.TRANSLATED, translation=translation)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.PENDING_FIRST_REVIEW)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.PROCESSING_SCRIPT)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.SCRIPT_READY, script=script)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.PENDING_TTS)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.PROCESSING_TTS)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.PENDING_SECOND_REVIEW, audio=audio)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    story = transition_story(story, StoryStatus.DONE)
    assert transition_story(story, StoryStatus.ARCHIVED).status is StoryStatus.ARCHIVED
    assert transition_story(story, StoryStatus.PENDING_SECOND_REVIEW).status is (
        StoryStatus.PENDING_SECOND_REVIEW
    )


def test_archive_retains_failure_evidence() -> None:
    failed = make_story().model_copy(
        update={
            "last_failure": PipelineFailure(
                code="tts_generation_failed",
                message="Fixture failure evidence.",
                retryable=True,
            )
        }
    )
    archived = transition_story(failed, StoryStatus.ARCHIVED)
    assert archived.last_failure == failed.last_failure


def test_audio_bundle_validates_complete_per_segment_voice_provenance() -> None:
    _, _, audio = make_artifacts()
    clip = audio.clips[0]
    digest = "0" * 64
    provenance = SegmentSynthesisProvenance(
        segment_id=clip.segment_id,
        speaker_id="narrator",
        emotion=SpeechEmotion.HAPPINESS,
        reference_audio_sha256=digest,
        reference_text_sha256=digest,
        gpt_weights_sha256=digest,
        sovits_weights_sha256=digest,
        model_identity="fixture-v1",
    )
    payload = audio.model_dump()
    payload["synthesis"]["segment_provenance"] = [provenance.model_dump()]
    audited = AudioBundle.model_validate(payload)
    assert audited.synthesis.segment_provenance == [provenance]

    payload["synthesis"]["segment_provenance"] = [
        provenance.model_dump(),
        provenance.model_dump(),
    ]
    with pytest.raises(ValidationError, match="unique per segment"):
        AudioBundle.model_validate(payload)
