from enum import StrEnum


class StoryStatus(StrEnum):
    FETCHED = "FETCHED"
    TRANSLATED = "TRANSLATED"
    PENDING_FIRST_REVIEW = "PENDING_FIRST_REVIEW"
    PROCESSING_SCRIPT = "PROCESSING_SCRIPT"
    SCRIPT_READY = "SCRIPT_READY"
    PENDING_SECOND_REVIEW = "PENDING_SECOND_REVIEW"
    DONE = "DONE"


class SourceKind(StrEnum):
    URL = "url"
    TEXT = "text"
    FIXED_SOURCE = "fixed_source"


class ReviewStage(StrEnum):
    FIRST = "first"
    SECOND = "second"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class AudioFormat(StrEnum):
    WAV = "wav"


class ContentCategory(StrEnum):
    KINDNESS = "kindness"
    CATS_DOGS = "cats_dogs"
    FORUM = "forum"
    SHORT_VIDEO = "short_video"
