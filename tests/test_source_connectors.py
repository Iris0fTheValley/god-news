from __future__ import annotations

import httpx
import pytest

from god_news.sources.collectors.connector_adapter import NasaConnectorCollectorAdapter
from god_news.sources.connectors.models import SourceFetchRequest
from god_news.sources.connectors.nasa import NasaRssConnector
from god_news.sources.connectors.registry import SourceConnectorRegistry

NASA_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:media="http://search.yahoo.com/mrss/">
 <channel>
  <title>NASA</title>
  <item>
   <title>NASA tests a quieter aircraft</title>
   <link>https://www.nasa.gov/aeronautics/quieter-aircraft/</link>
   <guid>nasa-story-1</guid>
   <dc:creator>NASA Editorial Team</dc:creator>
   <pubDate>Tue, 28 Jul 2026 04:01:00 +0000</pubDate>
   <category>Aeronautics</category>
   <description><![CDATA[<p>A successful test demonstrated quieter flight.</p>]]></description>
   <content:encoded><![CDATA[
    <p>A successful test demonstrated quieter flight for nearby communities.</p>
    <img src="https://images-assets.nasa.gov/image/test/test~large.jpg"
         alt="The research aircraft in flight" />
   ]]></content:encoded>
  </item>
  <item>
   <title>Students complete a space robotics challenge</title>
   <link>https://www.nasa.gov/learning-resources/robotics-challenge/</link>
   <guid>nasa-story-2</guid>
   <pubDate>Mon, 27 Jul 2026 04:01:00 +0000</pubDate>
   <description><![CDATA[<p>Student teams completed the challenge.</p>]]></description>
  </item>
 </channel>
</rss>
"""


def _client(payload: bytes = NASA_RSS, *, status: int = 200) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                content=payload,
                headers={"content-type": "application/rss+xml"},
                request=request,
            )
        )
    )


@pytest.mark.asyncio
async def test_nasa_connector_discovers_typed_articles_with_fail_closed_media_rights() -> None:
    async with _client() as client:
        connector = NasaRssConnector(
            client=client,
            endpoint="https://www.nasa.gov/feed/",
            enabled=True,
        )
        result = await connector.fetch(SourceFetchRequest(limit=1))

    assert connector.readiness().state == "ready"
    assert result.source == "nasa"
    assert result.next_cursor == "1"
    assert result.response_snapshot.byte_count == len(NASA_RSS)
    assert result.response_snapshot.content_sha256
    assert [article.external_id for article in result.articles] == ["nasa-story-1"]
    article = result.articles[0]
    assert "quieter flight" in article.content_text
    assert article.rights.status == "public_domain"
    assert article.rights.requires_human_review is False
    assert article.media_candidates[0].rights.status == "unknown"
    assert article.media_candidates[0].rights.requires_human_review is True
    assert article.media_candidates[0].direct_download_url is not None


@pytest.mark.asyncio
async def test_nasa_connector_supports_cursor_and_collector_compatibility() -> None:
    async with _client() as client:
        connector = NasaRssConnector(
            client=client,
            endpoint="https://www.nasa.gov/feed/",
            enabled=True,
        )
        registry = SourceConnectorRegistry([connector])
        second_page = await registry.fetch("nasa", SourceFetchRequest(limit=1, cursor="1"))
        collected = await NasaConnectorCollectorAdapter(
            registry.connector("nasa"),
            default_limit=2,
        ).collect()

    assert [article.external_id for article in second_page.articles] == ["nasa-story-2"]
    assert second_page.next_cursor is None
    assert collected.outcome == "succeeded"
    assert len(collected.items) == 2
    assert collected.items[0].source == "nasa"
    assert collected.items[0].rights.status == "unknown"
    assert collected.items[0].rights.allows_republication is False


@pytest.mark.asyncio
async def test_nasa_connector_classifies_invalid_xml_without_untyped_payloads() -> None:
    async with _client(b"<rss>") as client:
        connector = NasaRssConnector(
            client=client,
            endpoint="https://www.nasa.gov/feed/",
            enabled=True,
        )
        result = await connector.fetch(SourceFetchRequest(limit=1))

    assert result.articles == []
    assert result.errors[0].code == "nasa_rss_invalid_xml"
    assert result.attempts[0].outcome == "succeeded"


def test_connector_registry_rejects_duplicates_and_unknown_sources() -> None:
    connector = NasaRssConnector(
        client=_client(),
        endpoint="https://www.nasa.gov/feed/",
        enabled=True,
    )
    with pytest.raises(ValueError, match="already registered"):
        SourceConnectorRegistry([connector, connector])
    registry = SourceConnectorRegistry([connector])
    with pytest.raises(LookupError, match="no connector"):
        registry.connector("reddit")
