from __future__ import annotations

import pytest
from pydantic import ValidationError

from god_news.domain.enums import CaptionKind, SpeechEmotion
from god_news.domain.models import (
    CaptionVariant,
    IngestRequest,
    ScriptDocument,
    ScriptPreferences,
    ScriptSegment,
    TextSource,
)


def test_legacy_script_json_is_upgraded_to_structured_spoken_text() -> None:
    script = ScriptDocument.model_validate(
        {
            "revision": 1,
            "title": "Legacy script",
            "language": "zh-CN",
            "segments": [
                {
                    "sequence": 0,
                    "text": "旧口播",
                    "speaker_id": "narrator",
                    "emotion": "happiness",
                    "speed": 1.0,
                    "pitch": 0.0,
                }
            ],
        }
    )

    segment = script.segments[0]
    assert script.spoken_language == "zh-CN"
    assert segment.spoken_text == "旧口播"
    assert segment.spoken_language == "zh-CN"
    assert segment.captions == [
        CaptionVariant(
            language="zh-CN",
            kind=CaptionKind.VERBATIM,
            text="旧口播",
        )
    ]
    serialized = script.model_dump(mode="json")
    assert "language" not in serialized
    assert "text" not in serialized["segments"][0]


def test_verbatim_caption_must_match_tts_input_exactly() -> None:
    with pytest.raises(ValidationError, match="verbatim caption must exactly match"):
        ScriptSegment(
            sequence=0,
            spoken_text="Only this reaches TTS.",
            spoken_language="en-US",
            captions=[
                CaptionVariant(
                    language="en-US",
                    kind=CaptionKind.VERBATIM,
                    text="Different text",
                ),
                CaptionVariant(
                    language="zh-CN",
                    kind=CaptionKind.TRANSLATION,
                    text="只有英文会进入语音合成。",
                ),
            ],
            speaker_id="narrator",
            emotion=SpeechEmotion.HAPPINESS,
            speed=1.0,
            pitch=0.0,
        )


def test_short_narration_defaults_to_twenty_seconds_and_accepts_five() -> None:
    request = IngestRequest(source=TextSource(text="A small good-news item."))
    assert request.target_duration_seconds == 20

    preferences = ScriptPreferences(
        style="concise",
        target_duration_seconds=5,
        speaker_id="narrator",
    )
    assert preferences.target_duration_seconds == 5

    with pytest.raises(ValidationError):
        ScriptPreferences.model_validate(
            {**preferences.model_dump(), "target_duration_seconds": 4}
        )
