from __future__ import annotations

from typing import Literal

import httpx
from pydantic import ValidationError

from god_news.sources.collectors.models import CollectorReadiness, SourceCollectionRun
from god_news.sources.collectors.support import (
    CollectorFailure,
    RunRecorder,
    readiness_failure,
)
from god_news.sources.connectors.models import SourceArticle, SourceFetchRequest
from god_news.sources.connectors.protocols import SourceConnector
from god_news.sources.models import (
    RawNasaImage,
    RawNasaItem,
    RawNasaVideo,
    RawRightsDeclaration,
)


class NasaConnectorCollectorAdapter:
    """Compatibility adapter while source-run ingestion consumes raw source items."""

    source: Literal["nasa"] = "nasa"

    def __init__(self, connector: SourceConnector, *, default_limit: int) -> None:
        if connector.source != self.source:
            raise ValueError("NASA collector adapter requires a NASA connector")
        self._connector = connector
        self._default_limit = default_limit

    def readiness(self) -> CollectorReadiness:
        return self._connector.readiness()

    async def collect(self, *, limit: int | None = None) -> SourceCollectionRun:
        recorder = RunRecorder(self.source)
        unavailable = readiness_failure(self.readiness())
        if unavailable is not None:
            return recorder.fail_readiness(unavailable)
        requested_limit = self._default_limit if limit is None else limit
        if not 1 <= requested_limit <= 100:
            recorder.errors.append(
                CollectorFailure(
                    "invalid_collection_limit",
                    "NASA collection limit must be between 1 and 100.",
                ).evidence()
            )
            return recorder.finish(items=[])
        try:
            result = await self._connector.fetch(SourceFetchRequest(limit=requested_limit))
        except httpx.HTTPError:
            recorder.errors.append(
                CollectorFailure(
                    "nasa_rss_unreachable",
                    "NASA RSS could not be reached.",
                    retryable=True,
                ).evidence()
            )
            return recorder.finish(items=[])
        except (RuntimeError, ValueError):
            recorder.errors.append(
                CollectorFailure(
                    "nasa_connector_failed",
                    "NASA connector could not complete discovery.",
                    retryable=False,
                ).evidence()
            )
            return recorder.finish(items=[])

        for attempt in result.attempts:
            recorder.attempt(
                layer=f"nasa-{attempt.transport}",
                operation=attempt.operation,
                outcome=attempt.outcome,
                duration_ms=attempt.duration_ms,
                http_status=attempt.http_status,
                error_code=attempt.error_code,
                retryable=attempt.retryable,
                item_count=attempt.item_count,
            )
        recorder.errors.extend(
            CollectorFailure(
                error.code,
                error.message,
                retryable=error.retryable,
            ).evidence()
            for error in result.errors
        )
        items: list[RawNasaItem] = []
        for article in result.articles:
            try:
                items.append(self._to_raw_item(article))
            except (ValidationError, ValueError):
                recorder.errors.append(
                    CollectorFailure(
                        "nasa_article_adapter_invalid",
                        "A NASA article failed the compatibility contract.",
                    ).evidence()
                )
        return recorder.finish(items=list(items))

    @staticmethod
    def _to_raw_item(article: SourceArticle) -> RawNasaItem:
        media: list[RawNasaImage | RawNasaVideo] = []
        for candidate in article.media_candidates:
            download_url = candidate.direct_download_url
            if download_url is None or candidate.kind == "audio":
                continue
            if candidate.kind == "video":
                media.append(
                    RawNasaVideo(
                        url=download_url,
                        caption=candidate.title,
                        credit=candidate.credit,
                        duration_ms=candidate.duration_ms,
                    )
                )
            else:
                media.append(
                    RawNasaImage(
                        url=download_url,
                        alt_text=candidate.title,
                        credit=candidate.credit,
                        width=candidate.width,
                        height=candidate.height,
                    )
                )
        rights = article.rights
        # NASA's article-level public-domain policy does not prove that every
        # embedded image/video is NASA-owned. Collapse the compatibility
        # contract to uncertain rights whenever any retained media candidate
        # still requires review so downstream story-level media gates remain
        # fail-closed.
        media_rights_uncertain = any(
            candidate.direct_download_url is not None
            and candidate.kind != "audio"
            and (
                candidate.rights.requires_human_review
                or candidate.rights.status in {"unknown", "permission_required"}
            )
            for candidate in article.media_candidates
        )
        rights_status = "unknown" if media_rights_uncertain else rights.status
        return RawNasaItem(
            article_id=article.external_id,
            url=article.canonical_url,
            title=article.title,
            body=article.content_text,
            author=article.author,
            published_at=article.published_at,
            categories=article.categories,
            media=media,
            language=article.language,
            publisher=article.publisher,
            rights=RawRightsDeclaration(
                status=rights_status,
                copyright_holder=article.publisher,
                license_name=None if media_rights_uncertain else rights.license_identifier,
                license_url=None if media_rights_uncertain else rights.license_url,
                terms_url=rights.policy_url,
                allows_republication=(
                    False if media_rights_uncertain else rights.allows_commercial_use
                ),
                allows_derivatives=(
                    False if media_rights_uncertain else rights.allows_derivatives
                ),
                requires_attribution=(
                    True if media_rights_uncertain else rights.requires_attribution
                ),
            ),
        )
