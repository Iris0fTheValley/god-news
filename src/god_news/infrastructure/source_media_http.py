from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx

from god_news.domain.source_media import SourceMediaDownloader
from god_news.errors import FetchPolicyError, SourceMediaAcquisitionError
from god_news.infrastructure.fetchers.url_policy import UrlPolicy


class HttpSourceMediaDownloader(SourceMediaDownloader):
    """Stream stored source URLs without following unvalidated redirects."""

    def __init__(self, client: httpx.AsyncClient, policy: UrlPolicy) -> None:
        self._client = client
        self._policy = policy

    @asynccontextmanager
    async def stream(
        self,
        story_id: UUID,
        url: str,
    ) -> AsyncIterator[tuple[str, AsyncIterable[bytes]]]:
        try:
            await self._policy.validate(url)
        except FetchPolicyError as exc:
            raise SourceMediaAcquisitionError(
                story_id,
                "Source media URL was rejected by the outbound request policy.",
            ) from exc
        try:
            async with self._client.stream(
                "GET",
                url,
                headers={"Accept": "video/mp4,application/octet-stream;q=0.8"},
            ) as response:
                if response.is_redirect:
                    raise SourceMediaAcquisitionError(
                        story_id,
                        "Source media redirected; the redirected URL must be captured and "
                        "reviewed first.",
                    )
                if response.status_code != 200:
                    raise SourceMediaAcquisitionError(
                        story_id,
                        "Source media server returned an unsuccessful status.",
                        status_code=502,
                        retryable=response.status_code >= 500 or response.status_code == 429,
                    )
                content_type = response.headers.get("content-type", "application/octet-stream")
                yield content_type, response.aiter_bytes()
        except SourceMediaAcquisitionError:
            raise
        except httpx.HTTPError as exc:
            raise SourceMediaAcquisitionError(
                story_id,
                "Source media server could not be reached.",
                status_code=502,
                retryable=True,
            ) from exc
