from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from god_news.application.memory import MemoryCoordinator
from god_news.domain.models import MemoryItem, MemoryQuery, MemoryWrite
from god_news.infrastructure.memory import ChromaDBMemoryProvider, NoopMemoryProvider


class DeterministicEmbedding(EmbeddingFunction[Documents]):
    """Small local test embedding that cannot make network calls."""

    def __init__(self) -> None:
        self.thread_ids: list[int] = []

    def __call__(self, input: Documents) -> Embeddings:
        self.thread_ids.append(threading.get_ident())
        return [
            [
                1.0,
                float(len(text) % 17),
                float(sum(character.isalpha() for character in text) % 13),
                float(sum(ord(character) for character in text) % 19),
            ]
            for text in input
        ]

    @staticmethod
    def name() -> str:
        return "god-news-test-embedding-v1"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> DeterministicEmbedding:
        del config
        return DeterministicEmbedding()


class FilteringProvider:
    async def healthcheck(self) -> None:
        return None

    async def recall(self, query: MemoryQuery):  # type: ignore[no-untyped-def]
        del query
        return (
            MemoryItem(memory_id="draft", content="draft", score=1, approved=False),
            MemoryItem(memory_id="approved", content="approved", score=0.5, approved=True),
        )

    async def remember(self, memory: MemoryWrite) -> None:
        del memory

    async def aclose(self) -> None:
        return None


class FailingProvider:
    async def healthcheck(self) -> None:
        raise RuntimeError("healthcheck failed")

    async def recall(self, query: MemoryQuery):  # type: ignore[no-untyped-def]
        del query
        raise RuntimeError("recall failed")

    async def remember(self, memory: MemoryWrite) -> None:
        del memory
        raise RuntimeError("write failed")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_memory_coordinator_filters_unapproved_recall() -> None:
    coordinator = MemoryCoordinator(FilteringProvider(), recall_fail_open=False, recall_limit=5)
    recalled = await coordinator.recall("editorial style")
    assert [item.memory_id for item in recalled] == ["approved"]


@pytest.mark.asyncio
async def test_memory_fallbacks_are_explicit() -> None:
    noop = NoopMemoryProvider()
    await noop.healthcheck()
    assert await noop.recall(MemoryQuery(query="anything")) == ()
    await noop.aclose()


@pytest.mark.asyncio
async def test_memory_recall_policy_and_write_result_are_explicit() -> None:
    fail_open = MemoryCoordinator(FailingProvider(), recall_fail_open=True, recall_limit=5)
    assert await fail_open.recall("context") == ()

    fail_closed = MemoryCoordinator(FailingProvider(), recall_fail_open=False, recall_limit=5)
    with pytest.raises(RuntimeError, match="recall failed"):
        await fail_closed.recall("context")

    write = MemoryWrite(
        content="approved context",
        category="human_review",
        story_id=uuid4(),
        approved=True,
        source_hash="0" * 64,
    )
    assert not await fail_open.remember(write)


@pytest.mark.asyncio
async def test_chromadb_memory_is_persistent_filtered_and_idempotent(tmp_path: Path) -> None:
    embedding = DeterministicEmbedding()
    provider = ChromaDBMemoryProvider(
        persist_directory=tmp_path / "chroma",
        collection_name="test-memory-v1",
        embedding_function_name="default",
        embedding_model_name="all-MiniLM-L6-v2",
        embedding_function=embedding,
    )
    story_id = uuid4()
    approved = MemoryWrite(
        content="Approved editorial guidance about warm narration.",
        category="human_review",
        story_id=story_id,
        approved=True,
        source_hash="1" * 64,
    )
    draft = MemoryWrite(
        content="Unapproved draft guidance must stay private.",
        category="draft_script",
        story_id=story_id,
        approved=False,
        source_hash="2" * 64,
    )
    other_agent = MemoryWrite(
        content="Approved guidance belonging to a different agent.",
        agent_id="another-agent",
        category="human_review",
        story_id=story_id,
        approved=True,
        source_hash="3" * 64,
    )

    try:
        await provider.healthcheck()
        await provider.remember(approved)
        await provider.remember(approved)
        await provider.remember(draft)
        await provider.remember(other_agent)

        approved_results = await provider.recall(
            MemoryQuery(query="warm narration guidance", limit=10, approved_only=True)
        )
        assert [item.content for item in approved_results] == [approved.content]
        assert all(item.approved for item in approved_results)

        all_results = await provider.recall(
            MemoryQuery(query="guidance", limit=10, approved_only=False)
        )
        assert {item.content for item in all_results} == {approved.content, draft.content}
        assert embedding.thread_ids
        assert set(embedding.thread_ids) == {embedding.thread_ids[0]}
        assert embedding.thread_ids[0] != threading.get_ident()
    finally:
        await provider.aclose()

    reopened = ChromaDBMemoryProvider(
        persist_directory=tmp_path / "chroma",
        collection_name="test-memory-v1",
        embedding_function_name="default",
        embedding_model_name="all-MiniLM-L6-v2",
        embedding_function=DeterministicEmbedding(),
    )
    try:
        persisted = await reopened.recall(
            MemoryQuery(query="warm narration", limit=10, approved_only=True)
        )
        assert [item.content for item in persisted] == [approved.content]
    finally:
        await reopened.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        await reopened.healthcheck()
