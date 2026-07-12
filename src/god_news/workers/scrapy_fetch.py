from __future__ import annotations

# mypy: disable-error-code=misc
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import CloseSpider, IgnoreRequest
from scrapy.http import Request, Response, TextResponse
from scrapy.linkextractors import LinkExtractor
from trafilatura import bare_extraction

from god_news.infrastructure.fetchers.scrapy import ScrapyWorkerRequest, ScrapyWorkerResponse
from god_news.infrastructure.fetchers.url_policy import UrlPolicy, normalize_allowed_ports


class UrlSafetyDownloaderMiddleware:
    """Revalidates every Scrapy request, including redirects and robots.txt."""

    def __init__(self, allow_private: bool, allowed_ports: tuple[int, ...]) -> None:
        self._policy = UrlPolicy(allow_private=allow_private, allowed_ports=allowed_ports)

    @classmethod
    def from_crawler(cls, crawler: Any) -> UrlSafetyDownloaderMiddleware:
        return cls(
            allow_private=crawler.settings.getbool("GOD_NEWS_ALLOW_PRIVATE", False),
            allowed_ports=normalize_allowed_ports(
                crawler.settings.getlist("GOD_NEWS_ALLOWED_PORTS")
            ),
        )

    def process_request(self, request: Request) -> None:
        try:
            self._policy.validate_sync(request.url)
        except Exception as exc:
            raise IgnoreRequest("URL rejected by god-news network policy") from exc


@dataclass(slots=True)
class _ResultHolder:
    response: ScrapyWorkerResponse | None = None


def _run(request: ScrapyWorkerRequest) -> ScrapyWorkerResponse:
    holder = _ResultHolder()
    parsed = urlsplit(request.url)
    parsed_hostname = parsed.hostname
    if parsed_hostname is None:
        return ScrapyWorkerResponse(ok=False, error="Scrapy source has no hostname.")
    start_netloc = parsed.netloc

    class BoundedSiteSpider(scrapy.Spider):
        name = "god_news_bounded_site"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._links = LinkExtractor(allow_domains=(start_netloc,), unique=True)

        async def start(self):  # type: ignore[no-untyped-def]
            yield scrapy.Request(
                request.url,
                callback=self.parse,
                errback=self.on_error,
                dont_filter=True,
            )

        def parse(self, response: Response, **kwargs: Any):  # type: ignore[no-untyped-def]
            del kwargs
            if not isinstance(response, TextResponse):
                if holder.response is None:
                    holder.response = ScrapyWorkerResponse(
                        ok=False,
                        final_url=response.url,
                        error="Scrapy source was not a text document.",
                    )
                return
            document = bare_extraction(
                response.body,
                url=response.url,
                with_metadata=True,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
                deduplicate=True,
                fast=False,
            )
            if isinstance(document, dict):
                text = document.get("text")
                title = document.get("title")
                author = document.get("author")
                published_at = document.get("date")
            elif document is not None:
                text = document.text
                title = document.title
                author = document.author
                published_at = document.date
            else:
                text = title = author = published_at = None
            cleaned = text.strip() if isinstance(text, str) else ""
            if cleaned:
                candidate = ScrapyWorkerResponse(
                    ok=True,
                    final_url=response.url,
                    title=str(title) if title else response.css("title::text").get(),
                    content=cleaned,
                    author=str(author) if author else None,
                    published_at=published_at,
                )
                previous_size = (
                    len(holder.response.content)
                    if holder.response is not None and holder.response.content is not None
                    else 0
                )
                if len(cleaned) > previous_size:
                    holder.response = candidate
                if len(cleaned) >= request.min_content_characters:
                    raise CloseSpider("article_content_found")
            elif holder.response is None:
                holder.response = ScrapyWorkerResponse(
                    ok=False,
                    final_url=response.url,
                    error="Trafilatura could not extract a document.",
                )

            for link in self._links.extract_links(response):
                yield scrapy.Request(
                    link.url,
                    callback=self.parse,
                    errback=self.on_error,
                )

        def on_error(self, failure: Any) -> None:
            sys.stderr.write(f"Scrapy request error: {type(failure.value).__name__}\n")
            if holder.response is None:
                holder.response = ScrapyWorkerResponse(ok=False, error="Scrapy request failed.")

    process = CrawlerProcess(
        settings={
            "ROBOTSTXT_OBEY": True,
            "COOKIES_ENABLED": False,
            "DOWNLOAD_TIMEOUT": request.download_timeout_seconds,
            "DOWNLOAD_MAXSIZE": request.max_response_bytes,
            "REDIRECT_MAX_TIMES": request.redirect_max_times,
            "RETRY_TIMES": request.retry_times,
            "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
            "CONCURRENT_REQUESTS": 1,
            "DEPTH_LIMIT": request.depth_limit,
            "CLOSESPIDER_PAGECOUNT": request.close_page_count,
            "CLOSESPIDER_TIMEOUT": max(1, request.download_timeout_seconds * 2),
            "AUTOTHROTTLE_ENABLED": True,
            "USER_AGENT": request.user_agent,
            "GOD_NEWS_ALLOW_PRIVATE": request.allow_private,
            "GOD_NEWS_ALLOWED_PORTS": [str(port) for port in request.allowed_ports],
            "DOWNLOADER_MIDDLEWARES": {
                "god_news.workers.scrapy_fetch.UrlSafetyDownloaderMiddleware": 50,
            },
            "LOG_LEVEL": "WARNING",
        }
    )
    process.crawl(BoundedSiteSpider)
    process.start(stop_after_crawl=True, install_signal_handlers=False)
    return holder.response or ScrapyWorkerResponse(
        ok=False,
        error="Scrapy finished without producing a response.",
    )


def main() -> int:
    try:
        request = ScrapyWorkerRequest.model_validate_json(sys.stdin.buffer.read())
        result = _run(request)
    except Exception as exc:
        sys.stderr.write(f"Scrapy worker internal error: {type(exc).__name__}\n")
        result = ScrapyWorkerResponse(ok=False, error="Scrapy worker failed.")
    sys.stdout.write(result.model_dump_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
