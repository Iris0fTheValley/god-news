from __future__ import annotations

from collections.abc import Sequence

import httpx

from god_news.config import Settings
from god_news.infrastructure.fetchers.chain import FetcherChain
from god_news.sources.collectors.guardian import GuardianContentAPICollector
from god_news.sources.collectors.models import (
    CollectorDiagnostic,
    CollectorReadiness,
    SourceCollectionRun,
)
from god_news.sources.collectors.protocols import DiagnosableSourceCollector, SourceCollector
from god_news.sources.collectors.public_pages import (
    DazhongPublicPageCollector,
    PikabuPublicPageCollector,
)
from god_news.sources.collectors.reddit import RedditOAuthCollector
from god_news.sources.models import SourceName


class SourceCollectorRegistry:
    def __init__(self, collectors: Sequence[SourceCollector]) -> None:
        self._collectors: dict[SourceName, SourceCollector] = {}
        for collector in collectors:
            if collector.source in self._collectors:
                raise ValueError(f"collector already registered for {collector.source!r}")
            self._collectors[collector.source] = collector
        expected: set[SourceName] = {"dazhong", "reddit", "guardian", "pikabu"}
        if set(self._collectors) != expected:
            raise ValueError("collector registry requires each fixed source exactly once")

    def readiness(self) -> tuple[CollectorReadiness, ...]:
        order: tuple[SourceName, ...] = ("dazhong", "reddit", "guardian", "pikabu")
        return tuple(self._collectors[source].readiness() for source in order)

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun:
        return await self._collectors[source].collect(limit=limit)

    async def diagnose(self, source: SourceName) -> CollectorDiagnostic:
        collector = self._collectors[source]
        if not isinstance(collector, DiagnosableSourceCollector):
            return CollectorDiagnostic(source=source, outcome="not_supported")
        return await collector.diagnose()


def create_source_collectors(
    *,
    settings: Settings,
    client: httpx.AsyncClient,
    fetcher: FetcherChain,
) -> SourceCollectorRegistry:
    return SourceCollectorRegistry(
        (
            DazhongPublicPageCollector(
                fetcher=fetcher,
                endpoint=settings.source_dazhong_endpoint,
                enabled=settings.source_dazhong_enabled,
                public_page_use_authorized=(
                    settings.source_dazhong_public_page_use_authorized
                ),
                default_limit=settings.source_dazhong_collection_limit,
                allowed_host_suffixes=settings.source_dazhong_allowed_host_suffixes,
            ),
            RedditOAuthCollector(
                client=client,
                endpoint=settings.source_reddit_endpoint,
                token_endpoint=settings.source_reddit_token_endpoint,
                client_id=settings.source_reddit_client_id,
                client_secret=settings.source_reddit_client_secret,
                user_agent=settings.source_reddit_user_agent,
                enabled=settings.source_reddit_enabled,
                api_use_authorized=settings.source_reddit_api_use_authorized,
                subreddit=settings.source_reddit_subreddit,
                default_limit=settings.source_reddit_collection_limit,
            ),
            GuardianContentAPICollector(
                client=client,
                endpoint=settings.source_guardian_endpoint,
                api_key=settings.source_guardian_api_key,
                enabled=settings.source_guardian_enabled,
                ai_use_authorized=settings.source_guardian_ai_use_authorized,
                query=settings.source_guardian_query,
                section=settings.source_guardian_section,
                default_limit=settings.source_guardian_collection_limit,
            ),
            PikabuPublicPageCollector(
                fetcher=fetcher,
                endpoint=settings.source_pikabu_endpoint,
                enabled=settings.source_pikabu_enabled,
                public_page_use_authorized=settings.source_pikabu_public_page_use_authorized,
                default_limit=settings.source_pikabu_collection_limit,
                allowed_host_suffixes=settings.source_pikabu_allowed_host_suffixes,
            ),
        )
    )
