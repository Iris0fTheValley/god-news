from __future__ import annotations

import logging
from collections.abc import Sequence

from god_news.domain.models import MemoryItem, MemoryQuery, MemoryWrite
from god_news.domain.ports import MemoryProvider

logger = logging.getLogger(__name__)


class MemoryCoordinator:
    """Keeps recalled memory optional and external writes outside the FSM truth source."""

    def __init__(
        self,
        provider: MemoryProvider,
        *,
        recall_fail_open: bool,
        recall_limit: int,
    ) -> None:
        self._provider = provider
        self._recall_fail_open = recall_fail_open
        self._recall_limit = recall_limit

    async def recall(self, query: str) -> Sequence[MemoryItem]:
        try:
            recalled = await self._provider.recall(
                MemoryQuery(query=query, limit=self._recall_limit, approved_only=True)
            )
            return tuple(item for item in recalled if item.approved)
        except Exception:
            logger.exception("memory recall failed")
            if self._recall_fail_open:
                return ()
            raise

    async def remember(self, memory: MemoryWrite) -> bool:
        try:
            await self._provider.remember(memory)
            return True
        except Exception:
            logger.exception("memory write failed")
            # Writes happen after durable FSM commits. Never report a false workflow
            # failure after the story has already advanced; a future outbox adapter
            # can provide retryable, exactly-once delivery without coupling state.
            return False
