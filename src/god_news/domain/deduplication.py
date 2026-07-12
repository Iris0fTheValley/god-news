from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from god_news.domain.models import Story


@dataclass(frozen=True, slots=True)
class StoryIdentity:
    canonical_url_sha256: str | None
    content_sha256: str


def story_identity(story: Story) -> StoryIdentity:
    canonical_uri = story.canonical_source_uri
    canonical_hash = (
        sha256(canonical_uri.encode("utf-8")).hexdigest() if canonical_uri is not None else None
    )
    return StoryIdentity(
        canonical_url_sha256=canonical_hash,
        content_sha256=story.source.content_sha256,
    )
