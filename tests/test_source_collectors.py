from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from god_news.domain.enums import SourceKind
from god_news.domain.models import FetchedDocument, SourceSnapshot
from god_news.infrastructure.fetchers.telemetry import FetchLayerAttempt, TracedFetchResult
from god_news.sources.collectors.guardian import GuardianContentAPICollector
from god_news.sources.collectors.public_pages import (
    DazhongPublicPageCollector,
    PikabuPublicPageCollector,
)
from god_news.sources.collectors.reddit import RedditOAuthCollector


def _document(
    url: str,
    *,
    title: str,
    content: str,
    published_at: datetime | None = None,
) -> FetchedDocument:
    return FetchedDocument(
        source=SourceSnapshot(
            kind=SourceKind.URL,
            source_uri=url,
            final_uri=url,
            title=title,
            published_at=published_at,
            fetcher="fixture-layer",
            content_sha256="a" * 64,
        ),
        content=content,
    )


class ScriptedTracedFetcher:
    def __init__(self, documents: dict[str, FetchedDocument]) -> None:
        self.documents = documents
        self.calls: list[str] = []

    async def fetch_with_trace(self, source):  # type: ignore[no-untyped-def]
        url = str(source.url)
        self.calls.append(url)
        return TracedFetchResult(
            document=self.documents[url],
            attempts=(
                FetchLayerAttempt(
                    layer="jina-reader",
                    outcome="succeeded",
                    duration_ms=1.25,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_reddit_collector_uses_oauth_and_sanitizes_run_telemetry() -> None:
    secret = "reddit-secret-not-for-output"
    token = "oauth-token-not-for-output"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/access_token":
            expected = base64.b64encode(f"client-id:{secret}".encode()).decode()
            assert request.headers["Authorization"] == f"Basic {expected}"
            assert request.headers["User-Agent"] == "windows:god-news:v0.1 (by /u/tester)"
            assert request.content == b"grant_type=client_credentials"
            return httpx.Response(
                200,
                json={"access_token": token, "token_type": "bearer", "expires_in": 3600},
            )
        assert request.url.path == "/r/HumansBeingBros/new"
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "abc123",
                                "permalink": "/r/HumansBeingBros/comments/abc123/kind/",
                                "title": "A kind act",
                                "selftext": "A stranger helped a neighbour get home.",
                                "author": "kind_user",
                                "created_utc": 1_783_700_000,
                                "subreddit": "HumansBeingBros",
                                "score": 42,
                                "num_comments": 3,
                                "is_self": True,
                            },
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = RedditOAuthCollector(
            client=client,
            endpoint="https://oauth.reddit.com/",
            token_endpoint="https://www.reddit.com/api/v1/access_token",
            client_id=SecretStr("client-id"),
            client_secret=SecretStr(secret),
            user_agent="windows:god-news:v0.1 (by /u/tester)",
            enabled=True,
            api_use_authorized=True,
            subreddit="HumansBeingBros",
            default_limit=25,
        )
        run = await collector.collect(limit=1)

    assert run.outcome == "succeeded"
    assert [attempt.layer for attempt in run.attempts[:2]] == [
        "reddit-oauth",
        "reddit-data-api",
    ]
    assert run.items[0].source == "reddit"
    serialized = run.model_dump_json()
    assert secret not in serialized
    assert token not in serialized


@pytest.mark.asyncio
async def test_guardian_collector_maps_official_search_contract() -> None:
    api_key = "guardian-key-not-for-output"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["api-key"] == api_key
        assert request.url.params["show-fields"] == "body,byline,trailText,thumbnail"
        assert request.url.params["show-rights"] == "all"
        return httpx.Response(
            200,
            json={
                "response": {
                    "status": "ok",
                    "results": [
                        {
                            "id": "lifeandstyle/2026/jul/12/kindness",
                            "webUrl": "https://www.theguardian.com/lifeandstyle/2026/jul/12/kindness",
                            "webTitle": "A kindness story",
                            "webPublicationDate": "2026-07-12T08:00:00Z",
                            "sectionId": "lifeandstyle",
                            "pillarName": "Lifestyle",
                            "fields": {
                                "body": (
                                    "<p>A neighbour <strong>helped</strong>.</p>"
                                    "<p>Everyone was safe.</p>"
                                ),
                                "byline": "Fixture Reporter",
                                "trailText": "<p>A small act.</p>",
                                "thumbnail": "https://media.guim.co.uk/kindness.jpg",
                            },
                            "tags": [
                                {
                                    "id": "society/kindness",
                                    "webTitle": "Kindness",
                                    "type": "keyword",
                                }
                            ],
                        }
                    ],
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = GuardianContentAPICollector(
            client=client,
            endpoint="https://content.guardianapis.com/",
            api_key=SecretStr(api_key),
            enabled=True,
            ai_use_authorized=True,
            query="kindness",
            section="lifeandstyle",
            default_limit=25,
        )
        run = await collector.collect(limit=1)

    assert run.outcome == "succeeded"
    item = run.items[0]
    assert item.source == "guardian"
    assert item.body_text == "A neighbour helped.\n\nEveryone was safe."
    assert item.rights.status == "permission_required"
    assert api_key not in run.model_dump_json()


@pytest.mark.asyncio
async def test_dazhong_public_pages_use_existing_fetch_layers() -> None:
    listing_url = "https://m.dzplus.dzng.com/"
    story_url = "https://m.dzplus.dzng.com/share/general/0/NEWS123"
    fetcher = ScriptedTracedFetcher(
        {
            listing_url: _document(
                listing_url,
                title="大众新闻",
                content=f"[一则善意新闻]({story_url})",
            ),
            story_url: _document(
                story_url,
                title="陌生人伸出援手",
                content="一位陌生人停下来帮助老人, 家人随后表达了感谢。",
                published_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
            ),
        }
    )
    collector = DazhongPublicPageCollector(
        fetcher=fetcher,
        endpoint=listing_url,
        enabled=True,
        public_page_use_authorized=True,
        default_limit=10,
        allowed_host_suffixes=("dzng.com",),
    )

    run = await collector.collect(limit=1)

    assert run.outcome == "succeeded"
    assert fetcher.calls == [listing_url, story_url]
    assert [attempt.operation for attempt in run.attempts if attempt.layer == "jina-reader"] == [
        "discover",
        "item",
    ]
    assert run.items[0].source == "dazhong"


@pytest.mark.asyncio
async def test_pikabu_captcha_stops_before_remaining_story_urls() -> None:
    listing_url = "https://pikabu.ru/tag/%D0%94%D0%BE%D0%B1%D1%80%D0%BE%D1%82%D0%B0"
    first_url = "https://pikabu.ru/story/dobrota_12345"
    second_url = "https://pikabu.ru/story/help_67890"
    fetcher = ScriptedTracedFetcher(
        {
            listing_url: _document(
                listing_url,
                title="Доброта",
                content=f"[one]({first_url}) [two]({second_url})",
            ),
            first_url: _document(
                first_url,
                title="Проверка",
                content="Проверка, что вы не робот — CAPTCHA",
                published_at=datetime(2026, 7, 12, 9, tzinfo=UTC),
            ),
            second_url: _document(
                second_url,
                title="Not requested",
                content="This second story must not be requested.",
                published_at=datetime(2026, 7, 12, 10, tzinfo=UTC),
            ),
        }
    )
    collector = PikabuPublicPageCollector(
        fetcher=fetcher,
        endpoint=listing_url,
        enabled=True,
        public_page_use_authorized=True,
        default_limit=10,
        allowed_host_suffixes=("pikabu.ru",),
    )

    run = await collector.collect(limit=2)

    assert run.outcome == "stopped_captcha"
    assert fetcher.calls == [listing_url, first_url]
    assert run.errors[-1].code == "captcha_detected"
    assert run.attempts[-1].outcome == "stopped"


def test_collector_readiness_distinguishes_unconfigured_and_unauthorized() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    reddit = RedditOAuthCollector(
        client=client,
        endpoint="https://oauth.reddit.com/",
        token_endpoint="https://www.reddit.com/api/v1/access_token",
        client_id=None,
        client_secret=None,
        user_agent=None,
        enabled=True,
        api_use_authorized=False,
        subreddit="HumansBeingBros",
        default_limit=25,
    )
    guardian = GuardianContentAPICollector(
        client=client,
        endpoint="https://content.guardianapis.com/",
        api_key=SecretStr("configured"),
        enabled=True,
        ai_use_authorized=False,
        query="kindness",
        section=None,
        default_limit=25,
    )

    assert reddit.readiness().state == "unconfigured"
    assert guardian.readiness().state == "unauthorized"

    import asyncio

    asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_public_page_collector_rejects_wrong_listing_and_redirect_hosts() -> None:
    wrong_listing = DazhongPublicPageCollector(
        fetcher=ScriptedTracedFetcher({}),
        endpoint="https://example.com/news",
        enabled=True,
        public_page_use_authorized=True,
        default_limit=10,
        allowed_host_suffixes=("dzng.com",),
    )
    assert wrong_listing.readiness().state == "unconfigured"
    readiness_run = await wrong_listing.collect(limit=1)
    assert readiness_run.outcome == "unconfigured"

    requested = "https://m.dzplus.dzng.com/share/general/0/NEWS123"
    redirected = "https://example.com/copied-story"
    fetcher = ScriptedTracedFetcher(
        {
            requested: _document(
                redirected,
                title="Redirected content",
                content="Content from a host outside the source allowlist.",
                published_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
            )
        }
    )
    collector = DazhongPublicPageCollector(
        fetcher=fetcher,
        endpoint=requested,
        enabled=True,
        public_page_use_authorized=True,
        default_limit=10,
        allowed_host_suffixes=("dzng.com",),
    )
    redirected_run = await collector.collect(limit=1)
    assert redirected_run.outcome == "failed"
    assert redirected_run.errors[-1].code == "public_page_host_rejected"
    assert redirected_run.attempts[-1].layer == "dazhong-host-guard"
