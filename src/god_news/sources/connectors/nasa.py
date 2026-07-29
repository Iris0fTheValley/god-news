from __future__ import annotations

import asyncio
from datetime import UTC
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from time import perf_counter
from typing import ClassVar, Literal
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from pydantic import AnyHttpUrl

from god_news.sources.collectors.models import CollectorReadiness
from god_news.sources.collectors.support import readiness_for
from god_news.sources.connectors.models import (
    SourceArticle,
    SourceDiscoveryResult,
    SourceFetchAttempt,
    SourceFetchError,
    SourceFetchRequest,
    SourceMediaCandidate,
    SourceResponseSnapshot,
    SourceRightsAssessment,
)

_CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_MEDIA_NS = "http://search.yahoo.com/mrss/"
_NASA_MEDIA_POLICY = "https://www.nasa.gov/nasa-brand-center/images-and-media/"
_ALLOWED_ARTICLE_HOSTS = frozenset({"nasa.gov", "www.nasa.gov", "science.nasa.gov"})


class _ArticleHtmlParser(HTMLParser):
    _BLOCK_TAGS: ClassVar[frozenset[str]] = frozenset(
        {"article", "blockquote", "br", "div", "h1", "h2", "h3", "li", "p", "section"}
    )

    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._ignored_depth = 0
        self.parts: list[str] = []
        self.images: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        attributes = dict(attrs)
        if normalized in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if normalized in self._BLOCK_TAGS:
            self.parts.append("\n")
        if normalized == "img" and attributes.get("src"):
            source = urljoin(self._base_url, attributes["src"] or "")
            if _is_http_url(source):
                self.images.append((source, attributes.get("alt")))

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and normalized in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n\n".join(line for line in lines if line)


def _is_http_url(value: str) -> bool:
    return urlsplit(value).scheme.casefold() in {"http", "https"}


class NasaRssConnector:
    """Official, credential-free NASA RSS connector.

    RSS discovery and article text are usable without browser automation.
    Individual media candidates remain rights-review-required because NASA's
    policy explicitly excludes some third-party material.
    """

    source: Literal["nasa"] = "nasa"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint: str,
        enabled: bool,
        max_retries: int = 2,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._enabled = enabled
        self._max_retries = max_retries

    def readiness(self) -> CollectorReadiness:
        configured = _is_http_url(self._endpoint)
        return readiness_for(
            source=self.source,
            enabled=self._enabled,
            configured=configured,
            authorized=configured,
            notes=[
                "official_rss_feed",
                "credential_free",
                "browser_fallback_not_required",
                "per_media_rights_review_required",
            ],
        )

    async def fetch(self, request: SourceFetchRequest) -> SourceDiscoveryResult:
        if self.readiness().state != "ready":
            raise RuntimeError("NASA connector is not ready")
        offset = self._parse_cursor(request.cursor)
        attempts: list[SourceFetchAttempt] = []
        response = await self._request_feed(attempts)
        snapshot = SourceResponseSnapshot(
            endpoint=self._endpoint,
            content_type=response.headers.get("content-type"),
            byte_count=len(response.content),
            content_sha256=sha256(response.content).hexdigest(),
        )
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError:
            return SourceDiscoveryResult(
                source=self.source,
                errors=[
                    SourceFetchError(
                        code="nasa_rss_invalid_xml",
                        message="NASA RSS returned malformed XML.",
                        retryable=True,
                    )
                ],
                attempts=attempts,
                response_snapshot=snapshot,
            )

        elements = root.findall("./channel/item")
        selected = elements[offset : offset + request.limit]
        articles: list[SourceArticle] = []
        errors: list[SourceFetchError] = []
        for element in selected:
            item_started = perf_counter()
            try:
                articles.append(self._parse_item(element))
            except (ValueError, TypeError):
                external_id = self._text(element, "guid") or None
                errors.append(
                    SourceFetchError(
                        code="nasa_rss_item_invalid",
                        message="A NASA RSS item did not satisfy the connector contract.",
                        item_external_id=external_id,
                    )
                )
                attempts.append(
                    SourceFetchAttempt(
                        sequence=len(attempts),
                        operation="item",
                        transport="rss",
                        outcome="failed",
                        endpoint=self._endpoint,
                        duration_ms=(perf_counter() - item_started) * 1_000,
                        error_code="nasa_rss_item_invalid",
                        retryable=False,
                    )
                )
            else:
                attempts.append(
                    SourceFetchAttempt(
                        sequence=len(attempts),
                        operation="item",
                        transport="rss",
                        outcome="succeeded",
                        endpoint=self._endpoint,
                        duration_ms=(perf_counter() - item_started) * 1_000,
                        item_count=1,
                    )
                )

        if not selected:
            errors.append(
                SourceFetchError(
                    code="source_returned_no_items",
                    message="NASA RSS had no items at the requested cursor.",
                    retryable=False,
                )
            )
        next_offset = offset + len(selected)
        next_cursor = str(next_offset) if next_offset < len(elements) else None
        checkpoint = (
            max(article.published_at for article in articles).astimezone(UTC).isoformat()
            if articles
            else request.checkpoint
        )
        return SourceDiscoveryResult(
            source=self.source,
            articles=articles,
            errors=errors,
            attempts=attempts,
            response_snapshot=snapshot,
            next_cursor=next_cursor,
            checkpoint=checkpoint,
        )

    async def _request_feed(self, attempts: list[SourceFetchAttempt]) -> httpx.Response:
        for retry in range(self._max_retries + 1):
            started = perf_counter()
            try:
                response = await self._client.get(
                    self._endpoint,
                    headers={
                        "Accept": "application/rss+xml, application/xml;q=0.9",
                        "User-Agent": "god-news/0.1 (+source research pipeline)",
                    },
                )
            except httpx.HTTPError:
                attempts.append(
                    SourceFetchAttempt(
                        sequence=len(attempts),
                        operation="listing",
                        transport="rss",
                        outcome="failed",
                        endpoint=self._endpoint,
                        duration_ms=(perf_counter() - started) * 1_000,
                        error_code="nasa_rss_unreachable",
                        retryable=True,
                    )
                )
                if retry >= self._max_retries:
                    raise
            else:
                retryable = response.status_code == 429 or response.status_code >= 500
                attempts.append(
                    SourceFetchAttempt(
                        sequence=len(attempts),
                        operation="listing",
                        transport="rss",
                        outcome=("succeeded" if response.status_code == 200 else "failed"),
                        endpoint=self._endpoint,
                        duration_ms=(perf_counter() - started) * 1_000,
                        http_status=response.status_code,
                        error_code=(
                            None if response.status_code == 200 else "nasa_rss_http_error"
                        ),
                        retryable=(None if response.status_code == 200 else retryable),
                    )
                )
                if response.status_code == 200:
                    return response
                if not retryable or retry >= self._max_retries:
                    response.raise_for_status()
            await asyncio.sleep(min(2**retry, 4))
        raise AssertionError("retry loop must return or raise")

    def _parse_item(self, element: ElementTree.Element) -> SourceArticle:
        title = self._required_text(element, "title")
        link = self._required_text(element, "link")
        host = (urlsplit(link).hostname or "").casefold()
        if host not in _ALLOWED_ARTICLE_HOSTS:
            raise ValueError("NASA RSS article host is not allowlisted")
        guid = self._text(element, "guid") or link
        published_at = parsedate_to_datetime(self._required_text(element, "pubDate"))
        if published_at.tzinfo is None:
            raise ValueError("RSS publication time must be timezone-aware")
        author = self._text(element, f"{{{_DC_NS}}}creator") or None
        html = (
            self._text(element, f"{{{_CONTENT_NS}}}encoded")
            or self._required_text(element, "description")
        )
        parser = _ArticleHtmlParser(base_url=link)
        parser.feed(html)
        content = parser.text
        if not content:
            raise ValueError("RSS item body is empty")
        categories = [
            text
            for child in element.findall("category")
            if (text := (child.text or "").strip())
        ]
        raw_item = ElementTree.tostring(element, encoding="utf-8")
        media = self._media_candidates(element, parser, article_url=link, title=title)
        article_rights = SourceRightsAssessment(
            status="public_domain",
            policy_url=_NASA_MEDIA_POLICY,
            allows_commercial_use=True,
            allows_derivatives=True,
            requires_attribution=True,
            requires_human_review=False,
            trademark_warning=True,
            notes=[
                "NASA-authored material is generally not subject to US copyright",
                "NASA identifiers may not imply endorsement",
            ],
        )
        return SourceArticle(
            source=self.source,
            external_id=guid,
            canonical_url=link,
            title=title,
            content_text=content,
            published_at=published_at.astimezone(UTC),
            language="en-US",
            publisher="NASA",
            author=author,
            categories=categories,
            media_candidates=media,
            rights=article_rights,
            raw_item_sha256=sha256(raw_item).hexdigest(),
        )

    def _media_candidates(
        self,
        element: ElementTree.Element,
        parser: _ArticleHtmlParser,
        *,
        article_url: str,
        title: str,
    ) -> list[SourceMediaCandidate]:
        candidates: list[tuple[str, str | None, str | None]] = []
        for media in element.findall(f"{{{_MEDIA_NS}}}content"):
            if url := media.attrib.get("url"):
                candidates.append((url, media.attrib.get("type"), None))
        candidates.extend((url, None, alt) for url, alt in parser.images)
        result: list[SourceMediaCandidate] = []
        seen: set[str] = set()
        for url, mime_type, alt in candidates:
            if url in seen or not _is_http_url(url):
                continue
            seen.add(url)
            rights = SourceRightsAssessment(
                status="unknown",
                policy_url=_NASA_MEDIA_POLICY,
                requires_attribution=True,
                requires_human_review=True,
                personality_rights_warning=True,
                trademark_warning=True,
                notes=[
                    "NASA pages may contain third-party material",
                    "verify the individual media credit before publication",
                ],
            )
            result.append(
                SourceMediaCandidate(
                    kind=("video" if (mime_type or "").startswith("video/") else "image"),
                    canonical_source_url=article_url,
                    direct_download_url=AnyHttpUrl(url),
                    title=alt or title,
                    publisher="NASA",
                    mime_type=mime_type,
                    rights=rights,
                )
            )
            if len(result) >= 100:
                break
        return result

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            value = int(cursor)
        except ValueError as exc:
            raise ValueError("NASA RSS cursor must be a non-negative integer") from exc
        if value < 0:
            raise ValueError("NASA RSS cursor must be a non-negative integer")
        return value

    @staticmethod
    def _text(element: ElementTree.Element, path: str) -> str:
        child = element.find(path)
        return (child.text or "").strip() if child is not None else ""

    @classmethod
    def _required_text(cls, element: ElementTree.Element, path: str) -> str:
        value = cls._text(element, path)
        if not value:
            raise ValueError(f"NASA RSS item is missing {path}")
        return value
