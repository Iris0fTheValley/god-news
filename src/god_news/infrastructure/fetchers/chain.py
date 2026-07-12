from __future__ import annotations

import asyncio
from collections.abc import Sequence

from god_news.domain.models import FetchedDocument, SourceRequest, TextSource, UrlSource
from god_news.domain.ports import Fetcher
from god_news.errors import FetchError, FetchPolicyError


class TextFetcher:
    @property
    def name(self) -> str:
        return "text"

    async def fetch(self, source: SourceRequest) -> FetchedDocument:
        if not isinstance(source, TextSource):
            raise FetchError("Text fetcher only accepts text sources.", retryable=False)
        return FetchedDocument.from_text(source)

    async def aclose(self) -> None:
        return None


class FetcherChain:
    def __init__(self, url_fetchers: Sequence[Fetcher]) -> None:
        if not url_fetchers:
            raise ValueError("at least one URL fetcher is required")
        self._text_fetcher = TextFetcher()
        self._url_fetchers = tuple(url_fetchers)

    @property
    def name(self) -> str:
        return "fetcher-chain"

    async def fetch(self, source: SourceRequest) -> FetchedDocument:
        if isinstance(source, TextSource):
            return await self._text_fetcher.fetch(source)
        if not isinstance(source, UrlSource):
            raise FetchError("Unsupported source type.", retryable=False)

        failures: list[str] = []
        for fetcher in self._url_fetchers:
            try:
                return await fetcher.fetch(source)
            except FetchPolicyError:
                raise
            except asyncio.CancelledError:
                raise
            except FetchError as exc:
                failures.append(f"{fetcher.name}: {exc.public_message}")
            except Exception as exc:  # provider boundary: normalize unknown failures
                failures.append(f"{fetcher.name}: {type(exc).__name__}")
        detail = "; ".join(failures) if failures else "no fetcher attempted"
        raise FetchError(f"Every configured content fetcher failed ({detail}).")

    async def aclose(self) -> None:
        await asyncio.gather(
            *(fetcher.aclose() for fetcher in self._url_fetchers),
            return_exceptions=True,
        )
