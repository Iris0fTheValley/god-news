from __future__ import annotations

from uuid import UUID

from god_news.errors import GodNewsError


class SourceRunNotFoundError(GodNewsError):
    def __init__(self, run_id: UUID) -> None:
        del run_id
        super().__init__(
            "source_run_not_found",
            "Source collection run was not found.",
            status_code=404,
        )


class SourceRunConflictError(GodNewsError):
    def __init__(self) -> None:
        super().__init__(
            "source_run_conflict",
            "Source collection run changed concurrently; reload and retry.",
            status_code=409,
            retryable=True,
        )


class SourceRunCapacityError(GodNewsError):
    def __init__(self) -> None:
        super().__init__(
            "source_run_capacity_reached",
            "Too many source collection runs are queued; retry after one finishes.",
            status_code=429,
            retryable=True,
        )
