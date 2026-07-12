from __future__ import annotations

from types import MappingProxyType

from god_news.domain.enums import ReviewDecision, ReviewStage, StoryStatus
from god_news.domain.models import (
    AudioBundle,
    ReviewRecord,
    ScriptDocument,
    Story,
    TranslationResult,
    utc_now,
)
from god_news.errors import InvalidTransitionError, StoryInvariantError

_TRANSITIONS = MappingProxyType(
    {
        StoryStatus.FETCHED: frozenset({StoryStatus.TRANSLATED, StoryStatus.ARCHIVED}),
        StoryStatus.TRANSLATED: frozenset(
            {StoryStatus.PENDING_FIRST_REVIEW, StoryStatus.ARCHIVED}
        ),
        StoryStatus.PENDING_FIRST_REVIEW: frozenset(
            {StoryStatus.PROCESSING_SCRIPT, StoryStatus.ARCHIVED}
        ),
        StoryStatus.PROCESSING_SCRIPT: frozenset({StoryStatus.SCRIPT_READY, StoryStatus.ARCHIVED}),
        StoryStatus.SCRIPT_READY: frozenset(
            {StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.ARCHIVED}
        ),
        StoryStatus.PENDING_SECOND_REVIEW: frozenset({StoryStatus.DONE, StoryStatus.ARCHIVED}),
        StoryStatus.DONE: frozenset({StoryStatus.PENDING_SECOND_REVIEW, StoryStatus.ARCHIVED}),
        StoryStatus.ARCHIVED: frozenset(),
    }
)


def can_transition(current: StoryStatus, target: StoryStatus) -> bool:
    return target in _TRANSITIONS[current]


def transition_story(
    story: Story,
    target: StoryStatus,
    *,
    translation: TranslationResult | None = None,
    script: ScriptDocument | None = None,
    audio: AudioBundle | None = None,
) -> Story:
    if not can_transition(story.status, target):
        raise InvalidTransitionError(story.story_id, story.status, target)
    updates: dict[str, object] = {
        "status": target,
        "updated_at": utc_now(),
    }
    if target is not StoryStatus.ARCHIVED:
        updates["last_failure"] = None
    if translation is not None:
        updates["translation"] = translation
    if script is not None:
        updates["script"] = script
    if audio is not None:
        updates["audio"] = audio
    transitioned = story.model_copy(update=updates)
    validate_story_invariants(transitioned)
    return transitioned


def validate_story_invariants(story: Story) -> None:
    # ARCHIVED is a soft-delete terminal state.  It retains whatever valid
    # point-in-time artifacts existed before archival, so its requirements are
    # deliberately the union of every live pipeline state.
    if story.status is StoryStatus.ARCHIVED:
        return
    early_states = {
        StoryStatus.TRANSLATED,
        StoryStatus.PENDING_FIRST_REVIEW,
        StoryStatus.PROCESSING_SCRIPT,
    }
    if story.status is StoryStatus.FETCHED:
        if story.translation is not None or story.script is not None or story.audio is not None:
            raise StoryInvariantError(story.story_id, "FETCHED cannot contain generated artifacts.")
        return
    if story.translation is None:
        raise StoryInvariantError(story.story_id, f"{story.status} requires a translation.")
    if story.status in early_states:
        if story.script is not None or story.audio is not None:
            raise StoryInvariantError(
                story.story_id,
                f"{story.status} cannot contain script or audio artifacts.",
            )
        return
    if story.script is None:
        raise StoryInvariantError(story.story_id, f"{story.status} requires a script.")
    if story.status is StoryStatus.SCRIPT_READY:
        if story.audio is not None:
            raise StoryInvariantError(story.story_id, "SCRIPT_READY cannot contain audio.")
        return
    if story.status is StoryStatus.DONE and story.audio is None:
        raise StoryInvariantError(story.story_id, "DONE requires an audio bundle.")
    if story.audio is not None:
        script_ids = {segment.segment_id for segment in story.script.segments}
        audio_ids = {clip.segment_id for clip in story.audio.clips}
        if story.audio.revision != story.script.revision or script_ids != audio_ids:
            raise StoryInvariantError(
                story.story_id,
                "Script and audio revisions or segment sets do not match.",
            )


def validate_transition_evidence(
    current: StoryStatus,
    target: StoryStatus,
    story: Story,
    review: ReviewRecord | None,
) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(story.story_id, current, target)
    if review is not None and review.story_id != story.story_id:
        raise StoryInvariantError(
            story.story_id,
            "Review evidence belongs to a different story.",
        )
    if current is StoryStatus.PENDING_FIRST_REVIEW and target is StoryStatus.PROCESSING_SCRIPT:
        if (
            review is None
            or review.stage is not ReviewStage.FIRST
            or review.decision is not ReviewDecision.APPROVE
        ):
            raise InvalidTransitionError(story.story_id, current, target)
    if current is StoryStatus.SCRIPT_READY and target is StoryStatus.PENDING_SECOND_REVIEW:
        if story.audio is None:
            raise StoryInvariantError(story.story_id, "Second review requires generated audio.")
    if current is StoryStatus.PENDING_SECOND_REVIEW and target is StoryStatus.DONE:
        if (
            review is None
            or review.stage is not ReviewStage.SECOND
            or review.decision is not ReviewDecision.APPROVE
        ):
            raise InvalidTransitionError(story.story_id, current, target)


def all_transitions() -> tuple[tuple[StoryStatus, StoryStatus], ...]:
    return tuple((source, target) for source, targets in _TRANSITIONS.items() for target in targets)
