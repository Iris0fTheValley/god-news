from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Final, TypeVar, cast

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import (
    Documents,
    Embeddable,
    EmbeddingFunction,
    Metadata,
    QueryResult,
    Where,
)
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from god_news.domain.models import MemoryItem, MemoryQuery, MemoryWrite
from god_news.errors import ConfigurationError

_SCHEMA_VERSION: Final = 1
_DISTANCE_METRIC: Final = "cosine"
_T = TypeVar("_T")


class ChromaDBMemoryProvider:
    """Persistent semantic memory behind the asynchronous ``MemoryProvider`` port.

    Chroma's embedded client and embedding functions are synchronous. Every call,
    including lazy client construction, therefore runs on one private worker thread.
    Serial execution also gives deterministic lifecycle behaviour during shutdown.
    """

    def __init__(
        self,
        *,
        persist_directory: Path,
        collection_name: str,
        embedding_function_name: str,
        embedding_model_name: str,
        embedding_function: EmbeddingFunction[Documents] | None = None,
    ) -> None:
        self._persist_directory = persist_directory.resolve()
        self._collection_name = collection_name
        self._embedding_model_name = embedding_model_name
        self._embedding_function = cast(
            EmbeddingFunction[Embeddable],
            embedding_function
            or self._create_embedding_function(
                embedding_function_name,
                embedding_model_name,
            ),
        )
        self._embedding_function_name = self._embedding_function.name()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="god-news-chromadb",
        )
        self._operation_lock = asyncio.Lock()
        self._client: ClientAPI | None = None
        self._collection: Collection | None = None
        self._closed = False

    async def healthcheck(self) -> None:
        await self._run(self._healthcheck_sync)

    async def recall(self, query: MemoryQuery) -> Sequence[MemoryItem]:
        if query.limit == 0:
            return ()
        return await self._run(partial(self._recall_sync, query))

    async def remember(self, memory: MemoryWrite) -> None:
        await self._run(partial(self._remember_sync, memory))

    async def aclose(self) -> None:
        async with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            # PersistentClient has no public close method. Chroma persists writes
            # immediately; dropping references and stopping our worker is the complete
            # public lifecycle contract for the embedded client.
            self._collection = None
            self._client = None
            await asyncio.to_thread(
                self._executor.shutdown,
                wait=True,
                cancel_futures=True,
            )

    async def _run(self, operation: Callable[[], _T]) -> _T:
        async with self._operation_lock:
            if self._closed:
                raise RuntimeError("ChromaDB memory provider is closed.")
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, operation)

    def _healthcheck_sync(self) -> None:
        client, collection = self._ensure_collection_sync()
        heartbeat = client.heartbeat()
        if not isinstance(heartbeat, int) or heartbeat <= 0:
            raise ConfigurationError("ChromaDB returned an invalid heartbeat.")
        collection.count()

    def _remember_sync(self, memory: MemoryWrite) -> None:
        _, collection = self._ensure_collection_sync()
        memory_id = self._memory_id(memory)
        content_hash = hashlib.sha256(memory.content.encode("utf-8")).hexdigest()
        metadata: Metadata = {
            "schema_version": _SCHEMA_VERSION,
            "agent_id": memory.agent_id,
            "story_id": str(memory.story_id),
            "category": memory.category,
            "approved": memory.approved,
            "source_hash": memory.source_hash,
            "content_sha256": content_hash,
        }
        collection.upsert(
            ids=[memory_id],
            documents=[memory.content],
            metadatas=[metadata],
        )

    def _recall_sync(self, query: MemoryQuery) -> Sequence[MemoryItem]:
        _, collection = self._ensure_collection_sync()
        record_count = collection.count()
        if record_count == 0:
            return ()

        filters: list[dict[str, object]] = [{"agent_id": {"$eq": query.agent_id}}]
        if query.approved_only:
            filters.append({"approved": {"$eq": True}})
        where = cast(Where, filters[0] if len(filters) == 1 else {"$and": filters})
        result = collection.query(
            query_texts=[query.query],
            n_results=min(query.limit, record_count),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return self._parse_query_result(result, query)

    def _ensure_collection_sync(self) -> tuple[ClientAPI, Collection]:
        if self._client is not None and self._collection is not None:
            return self._client, self._collection

        self._persist_directory.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=self._persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        expected_metadata = self._expected_collection_metadata()
        collection = client.get_or_create_collection(
            name=self._collection_name,
            metadata=expected_metadata,
            embedding_function=self._embedding_function,
            configuration={"hnsw": {"space": _DISTANCE_METRIC}},
        )
        self._validate_collection_contract(collection, expected_metadata)
        self._client = client
        self._collection = collection
        return client, collection

    def _expected_collection_metadata(self) -> dict[str, Any]:
        return {
            "god_news_schema_version": _SCHEMA_VERSION,
            "embedding_function": self._embedding_function_name,
            "embedding_model": self._embedding_model_name,
            "distance_metric": _DISTANCE_METRIC,
        }

    @staticmethod
    def _validate_collection_contract(
        collection: Collection,
        expected_metadata: Mapping[str, object],
    ) -> None:
        actual_metadata = collection.metadata or {}
        for key, expected in expected_metadata.items():
            if actual_metadata.get(key) != expected:
                raise ConfigurationError(
                    "The existing ChromaDB collection has an incompatible memory schema. "
                    "Select a new collection name before changing its embedding contract."
                )
        hnsw = collection.configuration.get("hnsw")
        if not isinstance(hnsw, Mapping) or hnsw.get("space") != _DISTANCE_METRIC:
            raise ConfigurationError(
                "The existing ChromaDB collection does not use cosine distance."
            )

    @staticmethod
    def _parse_query_result(
        result: QueryResult,
        query: MemoryQuery,
    ) -> Sequence[MemoryItem]:
        ids_batches = result.get("ids") or []
        documents_batches = result.get("documents") or []
        metadata_batches = result.get("metadatas") or []
        distance_batches = result.get("distances") or []
        if not ids_batches:
            return ()
        if not documents_batches or not metadata_batches or not distance_batches:
            raise ConfigurationError("ChromaDB returned an incomplete memory query result.")

        ids = ids_batches[0]
        documents = documents_batches[0]
        metadatas = metadata_batches[0]
        distances = distance_batches[0]
        if not (len(ids) == len(documents) == len(metadatas) == len(distances)):
            raise ConfigurationError("ChromaDB returned misaligned memory query columns.")

        memories: list[MemoryItem] = []
        for memory_id, content, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
            strict=True,
        ):
            if content is None or metadata is None or distance is None:
                raise ConfigurationError("ChromaDB returned a malformed memory record.")
            approved = metadata.get("approved")
            agent_id = metadata.get("agent_id")
            category = metadata.get("category")
            if not isinstance(approved, bool) or not isinstance(agent_id, str):
                raise ConfigurationError("ChromaDB memory metadata has an invalid schema.")
            if agent_id != query.agent_id or (query.approved_only and not approved):
                raise ConfigurationError("ChromaDB violated the requested memory filter.")
            if not isinstance(category, str):
                category = None
            score = max(0.0, min(1.0, 1.0 - float(distance)))
            memories.append(
                MemoryItem(
                    memory_id=memory_id,
                    content=content,
                    score=score,
                    category=category,
                    approved=approved,
                )
            )
        return tuple(memories)

    @staticmethod
    def _memory_id(memory: MemoryWrite) -> str:
        canonical = json.dumps(
            memory.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"gnmem-v1-{digest}"

    @staticmethod
    def _create_embedding_function(
        name: str,
        model_name: str,
    ) -> EmbeddingFunction[Documents]:
        if name == DefaultEmbeddingFunction.name() and model_name == "all-MiniLM-L6-v2":
            return DefaultEmbeddingFunction()
        raise ConfigurationError(f"Unsupported local ChromaDB embedding function: {name!r}.")


class NoopMemoryProvider:
    """Explicit test/development fallback; production configuration rejects it."""

    async def healthcheck(self) -> None:
        return None

    async def recall(self, query: MemoryQuery) -> Sequence[MemoryItem]:
        del query
        return ()

    async def remember(self, memory: MemoryWrite) -> None:
        del memory

    async def aclose(self) -> None:
        return None
