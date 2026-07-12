from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from time import perf_counter
from typing import ClassVar, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from god_news.sources.collectors.models import CollectorReadiness, SourceCollectionRun
from god_news.sources.collectors.support import (
    CollectorFailure,
    RunRecorder,
    readiness_failure,
    readiness_for,
)
from god_news.sources.models import RawGuardianImage, RawGuardianItem, RawRightsDeclaration


class _HTMLTextExtractor(HTMLParser):
    _BLOCKS: ClassVar[frozenset[str]] = frozenset(
        {
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.casefold()
        if normalized in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and normalized in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and normalized in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(value)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


class _UpstreamModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Fields(_UpstreamModel):
    body: str | None = None
    byline: str | None = None
    trail_text: str | None = Field(default=None, validation_alias="trailText")
    thumbnail: str | None = None


class _Tag(_UpstreamModel):
    id: str | None = None
    web_title: str | None = Field(default=None, validation_alias="webTitle")
    type: str | None = None


class _GuardianResult(_UpstreamModel):
    id: str = Field(min_length=1)
    web_url: str = Field(min_length=1, validation_alias="webUrl")
    web_title: str = Field(min_length=1, validation_alias="webTitle")
    web_publication_date: datetime = Field(validation_alias="webPublicationDate")
    section_id: str | None = Field(default=None, validation_alias="sectionId")
    pillar_name: str | None = Field(default=None, validation_alias="pillarName")
    fields: _Fields = Field(default_factory=_Fields)
    tags: list[_Tag] = Field(default_factory=list)


class _GuardianResponse(_UpstreamModel):
    status: str
    results: list[_GuardianResult] = Field(default_factory=list)


class _GuardianEnvelope(_UpstreamModel):
    response: _GuardianResponse


class GuardianContentAPICollector:
    source: Literal["guardian"] = "guardian"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint: str,
        api_key: SecretStr | None,
        enabled: bool,
        ai_use_authorized: bool,
        query: str,
        section: str | None,
        default_limit: int,
    ) -> None:
        self._client = client
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._enabled = enabled
        self._ai_use_authorized = ai_use_authorized
        self._query = query.strip()
        self._section = section.strip() if section else None
        self._default_limit = default_limit

    def readiness(self) -> CollectorReadiness:
        configured = bool(self._api_key and self._query)
        return readiness_for(
            source=self.source,
            enabled=self._enabled,
            configured=configured,
            authorized=configured and self._ai_use_authorized,
            notes=[
                "official_content_api_only",
                "operator_authorization_must_cover_ai_and_derived_product_use",
                "commercial_tier_may_be_required",
                "per_item_rights_review_required",
            ],
        )

    async def collect(self, *, limit: int | None = None) -> SourceCollectionRun:
        recorder = RunRecorder(self.source)
        unavailable = readiness_failure(self.readiness())
        if unavailable is not None:
            return recorder.fail_readiness(unavailable)

        requested_limit = self._default_limit if limit is None else limit
        if not 1 <= requested_limit <= 50:
            recorder.errors.append(
                CollectorFailure(
                    "invalid_collection_limit",
                    "Guardian collection limit must be between 1 and 50.",
                ).evidence()
            )
            return recorder.finish(items=[])

        try:
            envelope = await self._search(requested_limit, recorder)
        except CollectorFailure as exc:
            recorder.errors.append(exc.evidence())
            return recorder.finish(items=[])

        items: list[RawGuardianItem] = []
        for result in envelope.response.results:
            started = perf_counter()
            try:
                item = self._map_result(result)
            except (ValidationError, ValueError):
                failure = CollectorFailure(
                    "guardian_item_contract_invalid",
                    "A Guardian result did not satisfy the typed source contract.",
                )
                recorder.errors.append(failure.evidence())
                recorder.attempt(
                    layer="guardian-contract-mapper",
                    operation="item",
                    outcome="failed",
                    duration_ms=(perf_counter() - started) * 1_000,
                    error_code=failure.code,
                )
            else:
                items.append(item)
                recorder.attempt(
                    layer="guardian-contract-mapper",
                    operation="item",
                    outcome="succeeded",
                    duration_ms=(perf_counter() - started) * 1_000,
                    item_count=1,
                )
        if not items and not recorder.errors:
            recorder.errors.append(
                CollectorFailure(
                    "source_returned_no_items",
                    "Guardian returned no content for the configured query.",
                ).evidence()
            )
        return recorder.finish(items=list(items))

    async def _search(self, limit: int, recorder: RunRecorder) -> _GuardianEnvelope:
        assert self._api_key is not None
        params: dict[str, str | int] = {
            "api-key": self._api_key.get_secret_value(),
            "q": self._query,
            "page-size": limit,
            "order-by": "newest",
            "show-fields": "body,byline,trailText,thumbnail",
            "show-tags": "contributor,keyword",
            "show-rights": "all",
        }
        if self._section:
            params["section"] = self._section
        started = perf_counter()
        try:
            response = await self._client.get(
                f"{self._endpoint}/search",
                params=params,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            failure = CollectorFailure(
                "guardian_api_unreachable",
                "Guardian Content API could not be reached.",
                retryable=True,
            )
            recorder.attempt(
                layer="guardian-content-api",
                operation="listing",
                outcome="failed",
                duration_ms=(perf_counter() - started) * 1_000,
                error_code=failure.code,
                retryable=True,
            )
            raise failure from exc
        if response.status_code != 200:
            failure = CollectorFailure(
                "guardian_api_http_error",
                "Guardian Content API returned an unsuccessful status.",
                retryable=response.status_code >= 500 or response.status_code == 429,
                http_status=response.status_code,
            )
            recorder.attempt(
                layer="guardian-content-api",
                operation="listing",
                outcome="failed",
                duration_ms=(perf_counter() - started) * 1_000,
                http_status=response.status_code,
                error_code=failure.code,
                retryable=failure.retryable,
            )
            raise failure
        try:
            envelope = _GuardianEnvelope.model_validate_json(response.content)
        except ValidationError as exc:
            failure = CollectorFailure(
                "guardian_api_contract_invalid",
                "Guardian Content API returned an unexpected response shape.",
            )
            recorder.attempt(
                layer="guardian-content-api",
                operation="listing",
                outcome="failed",
                duration_ms=(perf_counter() - started) * 1_000,
                http_status=response.status_code,
                error_code=failure.code,
            )
            raise failure from exc
        if envelope.response.status != "ok":
            failure = CollectorFailure(
                "guardian_api_contract_invalid",
                "Guardian Content API did not report an ok response.",
            )
            recorder.attempt(
                layer="guardian-content-api",
                operation="listing",
                outcome="failed",
                duration_ms=(perf_counter() - started) * 1_000,
                http_status=response.status_code,
                error_code=failure.code,
            )
            raise failure
        recorder.attempt(
            layer="guardian-content-api",
            operation="listing",
            outcome="succeeded",
            duration_ms=(perf_counter() - started) * 1_000,
            http_status=response.status_code,
            item_count=len(envelope.response.results),
        )
        return envelope

    @staticmethod
    def _map_result(result: _GuardianResult) -> RawGuardianItem:
        body_text = _html_to_text(result.fields.body)
        trail_text = _html_to_text(result.fields.trail_text) or None
        tags = [tag.id or tag.web_title for tag in result.tags if tag.id or tag.web_title]
        contributors = [
            tag.web_title
            for tag in result.tags
            if tag.type == "contributor" and tag.web_title
        ]
        byline = _html_to_text(result.fields.byline) or ", ".join(contributors) or None
        media: list[RawGuardianImage] = []
        if result.fields.thumbnail:
            media.append(
                RawGuardianImage(
                    url=result.fields.thumbnail,
                    role="thumbnail",
                )
            )
        return RawGuardianItem(
            article_id=result.id,
            web_url=result.web_url,
            web_title=result.web_title,
            body_text=body_text,
            byline=byline,
            web_publication_date=result.web_publication_date,
            section_id=result.section_id,
            pillar_name=result.pillar_name,
            trail_text=trail_text,
            tags=[tag for tag in tags if tag],
            media=media,
            language="en-GB",
            rights=RawRightsDeclaration(
                status="permission_required",
                copyright_holder="Guardian News & Media",
                terms_url="https://open-platform.theguardian.com/terms/",
                allows_republication=None,
                allows_derivatives=None,
                requires_attribution=True,
            ),
        )
