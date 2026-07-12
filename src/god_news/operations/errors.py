from __future__ import annotations

from uuid import UUID

from god_news.errors import GodNewsError


class RoleProfileNotFoundError(GodNewsError):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(
            "role_profile_not_found",
            "Role profile was not found.",
            status_code=404,
        )


class RoleProfileConflictError(GodNewsError):
    def __init__(
        self,
        message: str = "Role profile changed concurrently; reload and retry.",
    ) -> None:
        super().__init__("role_profile_conflict", message, status_code=409, retryable=True)


class OperationUnavailableError(GodNewsError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            "operation_unavailable",
            f"Operation '{operation}' has no configured handler.",
            status_code=503,
            retryable=True,
        )
