from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict

from god_news.domain.enums import SourceKind
from god_news.domain.models import FetchedDocument, SourceRequest, SourceSnapshot, UrlSource
from god_news.errors import FetchError
from god_news.infrastructure.fetchers.url_policy import UrlPolicy
from god_news.infrastructure.processes import run_json_worker


class DrissionWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    timeout_seconds: float
    base_timeout_seconds: float
    script_timeout_seconds: float
    quit_timeout_seconds: float
    max_response_bytes: int
    allow_private: bool
    allowed_ports: tuple[int, ...]


class DrissionWorkerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    final_url: str | None = None
    title: str | None = None
    html: str | None = None
    error: str | None = None


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


def _html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return "\n".join(parser.parts)


class DrissionPageFetcher:
    def __init__(
        self,
        *,
        policy: UrlPolicy,
        timeout_seconds: float,
        base_timeout_seconds: float,
        script_timeout_seconds: float,
        quit_timeout_seconds: float,
        max_concurrency: int,
        worker_module: str,
        max_response_bytes: int,
        min_content_characters: int,
    ) -> None:
        self._policy = policy
        self._timeout_seconds = timeout_seconds
        self._base_timeout_seconds = base_timeout_seconds
        self._script_timeout_seconds = script_timeout_seconds
        self._quit_timeout_seconds = quit_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._worker_module = worker_module
        self._max_response_bytes = max_response_bytes
        self._min_content_characters = min_content_characters

    @property
    def name(self) -> str:
        return "drission-page"

    async def fetch(self, source: SourceRequest) -> FetchedDocument:
        if not isinstance(source, UrlSource):
            raise FetchError("DrissionPage only accepts URL sources.", retryable=False)
        source_url = await self._policy.validate(str(source.url))
        request = DrissionWorkerRequest(
            url=source_url,
            timeout_seconds=self._timeout_seconds,
            base_timeout_seconds=self._base_timeout_seconds,
            script_timeout_seconds=self._script_timeout_seconds,
            quit_timeout_seconds=self._quit_timeout_seconds,
            max_response_bytes=self._max_response_bytes,
            allow_private=self._policy.allow_private,
            allowed_ports=self._policy.allowed_ports,
        )
        try:
            async with self._semaphore:
                response = await run_json_worker(
                    command=(sys.executable, "-m", self._worker_module),
                    request=request,
                    response_type=DrissionWorkerResponse,
                    timeout_seconds=self._timeout_seconds + 10,
                )
        except TimeoutError as exc:
            raise FetchError("DrissionPage exceeded its configured deadline.") from exc
        except Exception as exc:
            raise FetchError("DrissionPage worker failed to execute.") from exc
        if not response.ok or not response.final_url or response.html is None:
            raise FetchError(response.error or "DrissionPage failed to render the source.")
        final_url = await self._policy.validate(response.final_url)
        content = _html_to_text(response.html).strip()
        if len(content) < self._min_content_characters:
            raise FetchError("DrissionPage returned insufficient visible content.")
        return FetchedDocument(
            source=SourceSnapshot(
                kind=SourceKind.URL,
                source_uri=source_url,
                final_uri=final_url,
                title=(response.title or "").strip() or "Untitled source",
                fetcher=self.name,
                content_sha256=sha256(content.encode("utf-8")).hexdigest(),
            ),
            content=content,
        )

    async def aclose(self) -> None:
        return None
