from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from god_news.api.app import create_app
from god_news.domain.enums import StoryStatus
from god_news.domain.models import (
    FetchedDocument,
    ScriptPreferences,
    SourceItemIngestRequest,
    Story,
)
from god_news.errors import DuplicateStoryError
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.sources.models import RawDazhongItem, parse_raw_source_json
from god_news.sources.registry import create_default_source_registry

from .conftest import Stack

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _payload(source: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{source}.json").read_text(encoding="utf-8"))


def _request(source: str) -> SourceItemIngestRequest:
    return SourceItemIngestRequest(item=parse_raw_source_json(json.dumps(_payload(source))))


def _fetched_story(source: str) -> Story:
    normalized = create_default_source_registry().normalize(_request(source).item)
    fetched = FetchedDocument.from_normalized_source(normalized)
    return Story(
        status=StoryStatus.FETCHED,
        source=fetched.source,
        provenance=normalized,
        original_text=fetched.content,
        target_language="zh-CN",
        preferences=ScriptPreferences(
            style="deterministic fixture",
            target_duration_seconds=60,
            speaker_id="narrator",
        ),
    )


@pytest.mark.parametrize("source", ["dazhong", "reddit", "guardian", "pikabu"])
@pytest.mark.asyncio
async def test_each_fixed_source_enters_workflow_with_normalized_provenance(
    stack: Stack,
    source: str,
) -> None:
    story = await stack.workflow.ingest_source_item(_request(source))

    assert story.status is StoryStatus.PENDING_FIRST_REVIEW
    assert story.provenance is not None
    assert story.provenance.source == source
    assert story.source.kind.value == "fixed_source"
    assert story.source.final_uri == str(story.provenance.canonical_url)
    assert story.source.content_sha256 == story.provenance.content_sha256
    assert story.original_text == story.provenance.content_text
    assert story.provenance.attribution.original_url == story.provenance.canonical_url
    assert story.provenance.flags.requires_rights_review == (
        story.provenance.rights.requires_human_review
    )


@pytest.mark.asyncio
async def test_duplicate_source_item_is_rejected_before_second_llm_call(stack: Stack) -> None:
    request = _request("guardian")
    existing = await stack.workflow.ingest_source_item(request)
    translation_calls = stack.generator.translation_calls

    with pytest.raises(DuplicateStoryError) as caught:
        await stack.workflow.ingest_source_item(request)

    assert caught.value.story_id == existing.story_id
    assert "canonical URL" in caught.value.public_message
    assert stack.generator.translation_calls == translation_calls


@pytest.mark.asyncio
async def test_sql_repository_enforces_content_hash_deduplication(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'dedupe.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)
    try:
        first = _fetched_story("dazhong")
        await repository.create(first)
        persisted = await repository.get(first.story_id)
        assert persisted.provenance == first.provenance

        changed = _payload("dazhong")
        changed["article_id"] = "different-article-id"
        changed["url"] = "https://example.dzng.com/article/different"
        changed["canonical_url"] = "https://example.dzng.com/article/different"
        raw = parse_raw_source_json(json.dumps(changed))
        assert isinstance(raw, RawDazhongItem)
        normalized = create_default_source_registry().normalize(raw)
        fetched = FetchedDocument.from_normalized_source(normalized)
        duplicate_content = first.model_copy(
            update={
                "story_id": uuid4(),
                "trace_id": uuid4(),
                "source": fetched.source,
                "provenance": normalized,
                "original_text": fetched.content,
            }
        )

        with pytest.raises(DuplicateStoryError) as caught:
            await repository.create(duplicate_content)
        assert caught.value.story_id == first.story_id
        assert "normalized content" in caught.value.public_message
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_source_contract_and_health_are_exposed_by_api(stack: Stack) -> None:
    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/v1/sources/health")
            created = await client.post(
                "/api/v1/sources/items",
                json={"item": _payload("reddit"), "target_language": "zh-CN"},
            )

    assert health.status_code == 200
    report = health.json()
    assert report["network_probed"] is False
    assert [item["source"] for item in report["sources"]] == [
        "dazhong",
        "reddit",
        "guardian",
        "pikabu",
    ]
    assert all(item["contract_ok"] for item in report["sources"])
    assert all(item["reachable"] is None for item in report["sources"])
    assert created.status_code == 201
    assert created.json()["provenance"]["source"] == "reddit"
    assert created.json()["provenance"]["media"]
