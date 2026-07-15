from enum import StrEnum


class StoryStatus(StrEnum):
    FETCHED = "FETCHED"
    TRANSLATED = "TRANSLATED"
    PENDING_FIRST_REVIEW = "PENDING_FIRST_REVIEW"
    PROCESSING_SCRIPT = "PROCESSING_SCRIPT"
    SCRIPT_READY = "SCRIPT_READY"
    PENDING_TTS = "PENDING_TTS"
    PROCESSING_TTS = "PROCESSING_TTS"
    PENDING_SECOND_REVIEW = "PENDING_SECOND_REVIEW"
    DONE = "DONE"
    ARCHIVED = "ARCHIVED"


class SourceKind(StrEnum):
    URL = "url"
    TEXT = "text"
    FIXED_SOURCE = "fixed_source"


class ReviewStage(StrEnum):
    FIRST = "first"
    SCRIPT = "script"
    SECOND = "second"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class AudioFormat(StrEnum):
    WAV = "wav"


class SpeechEmotion(StrEnum):
    """The seven reference-voice emotions supported by the narration pipeline."""

    HAPPINESS = "happiness"
    SADNESS = "sadness"
    ANGER = "anger"
    DISGUST = "disgust"
    LIKE = "like"
    SURPRISE = "surprise"
    FEAR = "fear"


class SceneTransition(StrEnum):
    """Outgoing visual transition requested for a narration segment."""

    BLACK = "black"
    CROSSFADE = "crossfade"
    SLIDE = "slide"
    WIPE = "wipe"
    MOOD_SHIFT = "mood_shift"


class CaptionKind(StrEnum):
    VERBATIM = "verbatim"
    TRANSLATION = "translation"


class ContentCategory(StrEnum):
    KINDNESS = "kindness"
    CATS_DOGS = "cats_dogs"
    FORUM = "forum"
    SHORT_VIDEO = "short_video"
