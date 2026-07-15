from __future__ import annotations

from god_news.errors import GodNewsError


class SourceScheduleConflictError(GodNewsError):
    def __init__(self) -> None:
        super().__init__(
            "source_schedule_conflict",
            "The collection schedule changed concurrently; refresh and retry.",
            409,
        )
