from __future__ import annotations

import asyncio
from collections.abc import Sequence
from time import perf_counter

from god_news.domain.models import FetchedDocument, SourceRequest, TextSource, UrlSource
from god_news.domain.ports import Fetcher
from god_news.errors import FetchError, FetchPolicyError
from god_news.infrastructure.fetchers.telemetry import FetchLayerAttempt, TracedFetchResult


class TracedFetchError(FetchError):
    """Fetch failure that retains sanitized evidence for every attempted layer."""

    def __init__(self, message: str, attempts: tuple[FetchLayerAttempt, ...]) -> None:
        super().__init__(message)
        self.attempts = attempts


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
        return (await self.fetch_with_trace(source)).document

    async def fetch_with_trace(self, source: SourceRequest) -> TracedFetchResult:
        if isinstance(source, TextSource):
            started = perf_counter()
            document = await self._text_fetcher.fetch(source)
            return TracedFetchResult(
                document=document,
                attempts=(
                    FetchLayerAttempt(
                        layer=self._text_fetcher.name,
                        outcome="succeeded",
                        duration_ms=(perf_counter() - started) * 1_000,
                    ),
                ),
            )
        if not isinstance(source, UrlSource):
            raise FetchError("Unsupported source type.", retryable=False)

        failures: list[str] = []
        attempts: list[FetchLayerAttempt] = []
        for fetcher in self._url_fetchers:
            started = perf_counter()
            try:
                document = await fetcher.fetch(source)
            except FetchPolicyError:
                raise
            except asyncio.CancelledError:
                raise
            except FetchError as exc:
                failures.append(f"{fetcher.name}: {exc.public_message}")
                attempts.append(
                    FetchLayerAttempt(
                        layer=fetcher.name,
                        outcome="failed",
                        duration_ms=(perf_counter() - started) * 1_000,
                        error_code=exc.code,
                        retryable=exc.retryable,
                    )
                )
            except Exception as exc:  # provider boundary: normalize unknown failures
                failures.append(f"{fetcher.name}: {type(exc).__name__}")
                attempts.append(
                    FetchLayerAttempt(
                        layer=fetcher.name,
                        outcome="failed",
                        duration_ms=(perf_counter() - started) * 1_000,
                        error_code="unexpected_provider_error",
                    )
                )
            else:
                attempts.append(
                    FetchLayerAttempt(
                        layer=fetcher.name,
                        outcome="succeeded",
                        duration_ms=(perf_counter() - started) * 1_000,
                    )
                )
                return TracedFetchResult(document=document, attempts=tuple(attempts))
        detail = "; ".join(failures) if failures else "no fetcher attempted"
        raise TracedFetchError(
            f"Every configured content fetcher failed ({detail}).",
            tuple(attempts),
        )

    async def aclose(self) -> None:
        await asyncio.gather(
            *(fetcher.aclose() for fetcher in self._url_fetchers),
            return_exceptions=True,
        )
