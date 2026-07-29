"""Official Wikimedia Commons API adapter with a conservative licence allowlist."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from god_news.domain.visual_discovery import (
    CommonsAttribution,
    CommonsDiscoveryRequest,
    CommonsDiscoveryResult,
    CommonsLicense,
    CommonsMediaKind,
    CommonsRights,
    CommonsVideoDerivative,
    CommonsVisualCandidate,
)
from god_news.domain.visual_discovery_ports import VisualDiscoveryService

_API_URL = "https://commons.wikimedia.org/w/api.php"
_COMMONS_HOST = "commons.wikimedia.org"
_UPLOAD_HOST = "upload.wikimedia.org"


class WikimediaCommonsError(RuntimeError):
    """The official API response was unavailable or could not be trusted."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _ApiMetadataValue(_ApiModel):
    value: str | int | float | bool = ""


class _ApiDerivative(_ApiModel):
    src: str | None = None
    type: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    bandwidth: int | None = Field(default=None, gt=0)


class _ApiFileInfo(_ApiModel):
    url: str | None = None
    mime: str | None = None
    size: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    sha1: str | None = None
    duration: float | None = Field(default=None, gt=0)
    extmetadata: dict[str, _ApiMetadataValue] = Field(default_factory=dict)
    derivatives: list[_ApiDerivative] = Field(default_factory=list)


class _ApiPage(_ApiModel):
    pageid: int | None = Field(default=None, ge=1)
    title: str | None = None
    missing: bool = False
    imageinfo: list[_ApiFileInfo] = Field(default_factory=list)
    videoinfo: list[_ApiFileInfo] = Field(default_factory=list)


class _ApiQuery(_ApiModel):
    pages: list[_ApiPage] = Field(default_factory=list)


class _ApiResponse(_ApiModel):
    query: _ApiQuery | None = None


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @property
    def value(self) -> str:
        return " ".join("".join(self.parts).split())


class WikimediaCommonsClient(VisualDiscoveryService):
    """Read public, official Commons metadata without accepting client-supplied URLs.

    The client uses imageinfo first to find image/video files, then asks the
    documented TimedMediaHandler videoinfo endpoint only for video derivatives.
    It never trusts an arbitrary download or licence value supplied by a caller.
    """

    def __init__(self, client: httpx.AsyncClient, *, user_agent: str = "god-news/0.1") -> None:
        self._client = client
        self._user_agent = user_agent

    async def discover(self, request: CommonsDiscoveryRequest) -> CommonsDiscoveryResult:
        image_pages = await self._query(self._imageinfo_params(request))
        video_page_ids = [
            page.pageid for page in image_pages if page.pageid is not None and _page_is_video(page)
        ]
        video_info_by_page = await self._video_info(video_page_ids)
        candidates: list[CommonsVisualCandidate] = []
        for page in image_pages:
            if page.pageid is None:
                raise WikimediaCommonsError("Commons result did not include a page id")
            try:
                candidates.append(
                    self._build_initial(page, video_info=video_info_by_page.get(page.pageid))
                )
            except WikimediaCommonsError:
                if request.query is None:
                    raise
                # Search is exploratory and Commons can mix documents, audio,
                # or malformed legacy records into otherwise useful results.
                # Invalid items remain unavailable; exact File/page resolution
                # still fails closed during staging.
                continue
        return CommonsDiscoveryResult(request=request, candidates=candidates)

    async def _query(self, params: dict[str, str | int]) -> list[_ApiPage]:
        try:
            response = await self._client.get(
                _API_URL,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self._user_agent,
                    "Api-User-Agent": self._user_agent,
                },
            )
            response.raise_for_status()
            payload = _ApiResponse.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise WikimediaCommonsError(
                f"Wikimedia Commons API returned HTTP {status}",
                status_code=status,
                retryable=status >= 500 or status == 429,
            ) from exc
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise WikimediaCommonsError(
                "Wikimedia Commons API response could not be validated"
            ) from exc
        final_host = (urlsplit(str(response.url)).hostname or "").casefold()
        if final_host != _COMMONS_HOST or urlsplit(str(response.url)).scheme.casefold() != "https":
            raise WikimediaCommonsError("Wikimedia Commons API left the official HTTPS host")
        return [page for page in (payload.query.pages if payload.query else []) if not page.missing]

    @staticmethod
    def _imageinfo_params(request: CommonsDiscoveryRequest) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|dimensions|sha1|extmetadata",
        }
        if request.query is not None:
            params.update(
                {
                    "generator": "search",
                    "gsrsearch": request.query,
                    "gsrnamespace": 6,
                    "gsrlimit": request.limit,
                }
            )
        elif request.file_title is not None:
            params["titles"] = request.file_title
        else:
            params["pageids"] = request.page_id or 0
        return params

    async def _video_info(self, page_ids: list[int]) -> dict[int, _ApiFileInfo]:
        if not page_ids:
            return {}
        pages = await self._query(
            {
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "prop": "videoinfo",
                "viprop": "url|mime|size|dimensions|sha1|duration|extmetadata|derivatives",
                "pageids": "|".join(str(page_id) for page_id in page_ids),
            }
        )
        information: dict[int, _ApiFileInfo] = {}
        for page in pages:
            if page.pageid is None or not page.videoinfo:
                continue
            information[page.pageid] = page.videoinfo[0]
        return information

    def _build_initial(
        self,
        page: _ApiPage,
        *,
        video_info: _ApiFileInfo | None,
    ) -> CommonsVisualCandidate:
        if page.pageid is None or not page.title or not page.imageinfo:
            raise WikimediaCommonsError("Commons result did not include usable file metadata")
        info = page.imageinfo[0]
        url = info.url
        mime = info.mime
        size = info.size
        width = info.width
        height = info.height
        sha1 = info.sha1
        if (
            url is None
            or mime is None
            or size is None
            or width is None
            or height is None
            or sha1 is None
        ):
            raise WikimediaCommonsError("Commons file metadata was incomplete")
        direct_url = _official_upload_url(url)
        candidate_mime = video_info.mime if video_info is not None and video_info.mime else mime
        if (
            candidate_mime.casefold() == "application/ogg"
            and page.title.casefold().endswith((".ogv", ".ogg"))
            and video_info is not None
            and video_info.duration is not None
        ):
            candidate_mime = "video/ogg"
        kind = _media_kind(
            candidate_mime,
            is_timed_ogg=(
                video_info is not None
                and page.title.casefold().endswith((".ogv", ".ogg"))
                and video_info.duration is not None
            ),
        )
        duration_seconds = info.duration
        if kind is CommonsMediaKind.VIDEO and video_info is not None:
            duration_seconds = video_info.duration or duration_seconds
        duration_ms = _duration_ms(duration_seconds) if kind is CommonsMediaKind.VIDEO else None
        if kind is CommonsMediaKind.VIDEO and duration_ms is None:
            # imageinfo does not promise duration for every video. A second,
            # official videoinfo lookup is mandatory before accepting it.
            raise WikimediaCommonsError("Commons video metadata did not include a duration")
        metadata = info.extmetadata
        attribution = _attribution(metadata, page.title)
        rights = _rights(metadata, has_attribution=attribution.author is not None)
        try:
            return CommonsVisualCandidate(
                file_title=page.title,
                page_id=page.pageid,
                canonical_page_url=_canonical_page_url(page.title),
                direct_download_url=direct_url,
                kind=kind,
                mime_type=candidate_mime,
                width=width,
                height=height,
                duration_ms=duration_ms,
                size_bytes=size,
                sha1=sha1.casefold(),
                attribution=attribution,
                rights=rights,
                video_derivatives=(
                    self._parse_derivatives(video_info.derivatives)
                    if video_info is not None
                    else []
                ),
            )
        except ValidationError as exc:
            raise WikimediaCommonsError(
                "Commons file metadata did not satisfy the visual contract"
            ) from exc

    @staticmethod
    def _parse_derivatives(items: list[_ApiDerivative]) -> list[CommonsVideoDerivative]:
        derivatives: list[CommonsVideoDerivative] = []
        for item in items:
            src = item.src
            mime_type = item.type
            width = item.width
            height = item.height
            if src is None or mime_type is None or width is None or height is None:
                continue
            if not mime_type.casefold().startswith("video/"):
                continue
            try:
                derivatives.append(
                    CommonsVideoDerivative(
                        url=_official_upload_url(src),
                        mime_type=mime_type,
                        width=width,
                        height=height,
                        bandwidth=item.bandwidth,
                    )
                )
            except (ValidationError, WikimediaCommonsError):
                continue
        return derivatives


def _official_upload_url(value: str) -> AnyHttpUrl:
    try:
        parsed = AnyHttpUrl(value)
    except ValidationError as exc:
        raise WikimediaCommonsError("Commons returned an invalid upload URL") from exc
    split = urlsplit(str(parsed))
    if split.scheme.casefold() != "https" or (split.hostname or "").casefold() != _UPLOAD_HOST:
        raise WikimediaCommonsError("Commons returned a non-official upload URL")
    return parsed


def _canonical_page_url(file_title: str) -> AnyHttpUrl:
    title = quote(file_title.replace(" ", "_"), safe=":_")
    return AnyHttpUrl(f"https://{_COMMONS_HOST}/wiki/{title}")


def _media_kind(mime_type: str, *, is_timed_ogg: bool = False) -> CommonsMediaKind:
    mime = mime_type.casefold()
    if mime.startswith("image/"):
        return CommonsMediaKind.IMAGE
    if mime.startswith("video/"):
        return CommonsMediaKind.VIDEO
    if mime == "application/ogg" and is_timed_ogg:
        return CommonsMediaKind.VIDEO
    raise WikimediaCommonsError("Commons result was neither a supported image nor video")


def _page_is_video(page: _ApiPage) -> bool:
    if not page.imageinfo:
        return False
    mime_type = page.imageinfo[0].mime
    if mime_type is None:
        return False
    mime = mime_type.casefold()
    return mime.startswith("video/") or (
        mime == "application/ogg"
        and page.title is not None
        and page.title.casefold().endswith((".ogv", ".ogg"))
        and page.imageinfo[0].width is not None
        and page.imageinfo[0].height is not None
    )


def _duration_ms(value: float | None) -> int | None:
    if value is None:
        return None
    milliseconds = round(value * 1_000)
    return milliseconds if milliseconds > 0 else None


def _metadata_value(metadata: dict[str, _ApiMetadataValue], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    plain = _strip_html(str(value.value))
    return plain or None


def _strip_html(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return parser.value


def _metadata_url(metadata: dict[str, _ApiMetadataValue], key: str) -> AnyHttpUrl | None:
    value = _metadata_value(metadata, key)
    if value is None:
        return None
    try:
        return AnyHttpUrl(value)
    except ValidationError:
        return None


def _attribution(
    metadata: dict[str, _ApiMetadataValue],
    file_title: str,
) -> CommonsAttribution:
    author = _metadata_value(metadata, "Artist")
    credit = _metadata_value(metadata, "Credit")
    attribution = _metadata_value(metadata, "Attribution")
    return CommonsAttribution(
        author=author,
        credit=credit,
        attribution_text=attribution or author or credit or f"Wikimedia Commons: {file_title}",
    )


def _rights(
    metadata: dict[str, _ApiMetadataValue],
    *,
    has_attribution: bool,
) -> CommonsRights:
    label = _metadata_value(metadata, "LicenseShortName") or _metadata_value(metadata, "UsageTerms")
    license_url = _metadata_url(metadata, "LicenseUrl")
    license = _map_license(label)
    if license is CommonsLicense.UNKNOWN:
        return CommonsRights(
            license=license,
            source_license_label=label,
            license_url=license_url,
            allows_commercial_use=False,
            allows_derivatives=False,
            requires_attribution=True,
            requires_human_review=True,
        )
    requires_attribution = license in {CommonsLicense.CC_BY, CommonsLicense.CC_BY_SA}
    return CommonsRights(
        license=license,
        source_license_label=label,
        license_url=license_url,
        allows_commercial_use=True,
        allows_derivatives=True,
        requires_attribution=requires_attribution,
        requires_human_review=requires_attribution and not has_attribution,
    )


def _map_license(label: str | None) -> CommonsLicense:
    if not label:
        return CommonsLicense.UNKNOWN
    normalized = " ".join(label.upper().replace("-", " ").split())
    if "NC" in normalized or "ND" in normalized:
        return CommonsLicense.UNKNOWN
    if "CC0" in normalized:
        return CommonsLicense.CC0
    if "PUBLIC DOMAIN" in normalized or normalized.startswith("PD ") or normalized == "PD":
        return CommonsLicense.PUBLIC_DOMAIN
    if "CC BY SA" in normalized:
        return CommonsLicense.CC_BY_SA
    if "CC BY" in normalized:
        return CommonsLicense.CC_BY
    return CommonsLicense.UNKNOWN
