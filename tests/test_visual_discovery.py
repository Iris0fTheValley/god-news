from __future__ import annotations

import hashlib

import httpx
import pytest
from pydantic import ValidationError

from god_news.application.visual_discovery import VisualDiscoveryApplication
from god_news.domain.enums import StoryStatus
from god_news.domain.fsm import transition_story
from god_news.domain.visual_discovery import (
    CommonsDiscoveryRequest,
    CommonsLicense,
    CommonsMediaKind,
    CommonsRights,
    CommonsVisualCandidate,
    PersistedVisualDiscoveryAsset,
    StageCommonsVisualRequest,
    VisualDiscoveryReviewRequest,
    VisualDiscoveryStatus,
)
from god_news.errors import StoryInvariantError
from god_news.infrastructure.testing import InMemoryStoryRepository
from god_news.infrastructure.visual_discovery_store import LocalVisualDiscoveryStore
from god_news.infrastructure.wikimedia_commons import WikimediaCommonsClient, WikimediaCommonsError

from .test_fsm import make_artifacts, make_story


def _image_response(*, license_name: str = "CC BY 4.0") -> dict[str, object]:
    return {
        "query": {
            "pages": [
                {
                    "pageid": 123,
                    "title": "File:Solar eclipse.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/eclipse.jpg",
                            "mime": "image/jpeg",
                            "size": 321,
                            "width": 1280,
                            "height": 720,
                            "sha1": "a" * 40,
                            "extmetadata": {
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {
                                    "value": "https://creativecommons.org/licenses/by/4.0/"
                                },
                                "Artist": {"value": "<b>NASA</b>"},
                                "Credit": {"value": "NASA image"},
                            },
                        }
                    ],
                }
            ]
        }
    }


def _video_response() -> dict[str, object]:
    return {
        "query": {
            "pages": [
                {
                    "pageid": 456,
                    "title": "File:Moon transit.webm",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/moon.webm",
                            "mime": "video/webm",
                            "size": 654,
                            "width": 1920,
                            "height": 1080,
                            "sha1": "b" * 40,
                            "extmetadata": {
                                "LicenseShortName": {"value": "Public domain"},
                                "Artist": {"value": "NASA"},
                            },
                        }
                    ],
                }
            ]
        }
    }


def _video_info_response() -> dict[str, object]:
    return {
        "query": {
            "pages": [
                {
                    "pageid": 456,
                    "title": "File:Moon transit.webm",
                    "videoinfo": [
                        {
                            "duration": 4.25,
                            "derivatives": [
                                {
                                    "src": "https://upload.wikimedia.org/wikipedia/commons/transcoded/a/a1/moon.webm/moon.720p.mp4",
                                    "type": "video/mp4",
                                    "width": 1280,
                                    "height": 720,
                                    "bandwidth": 900000,
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }


def _client(payloads: list[dict[str, object]]) -> httpx.AsyncClient:
    calls = iter(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        assert request.url.host == "commons.wikimedia.org"
        assert request.headers["api-user-agent"] == "test-agent/1.0 (contact: test)"
        return httpx.Response(200, json=next(calls), request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _commons_client(http_client: httpx.AsyncClient) -> WikimediaCommonsClient:
    return WikimediaCommonsClient(http_client, user_agent="test-agent/1.0 (contact: test)")


_MINIMAL_JPEG = (
    b"\xff\xd8"
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    b"\xff\xd9"
)


class _OneCandidateDiscovery:
    def __init__(self, candidate: CommonsVisualCandidate) -> None:
        self._candidate = candidate

    async def discover(self, request: CommonsDiscoveryRequest):
        return type("Result", (), {"candidates": [self._candidate]})()


class _DiscoveryRepository:
    def __init__(self) -> None:
        self.assets: dict[object, PersistedVisualDiscoveryAsset] = {}

    async def create(self, asset: PersistedVisualDiscoveryAsset) -> None:
        self.assets[asset.asset_id] = asset

    async def get(self, asset_id):
        return self.assets[asset_id]

    async def list_for_story(self, story_id, *, script_revision):
        return [
            asset
            for asset in self.assets.values()
            if asset.story_id == story_id and asset.script_revision == script_revision
        ]

    async def set_status(self, asset_id, *, status, review_note):
        asset = self.assets[asset_id].model_copy(
            update={"status": VisualDiscoveryStatus(status), "review_note": review_note}
        )
        self.assets[asset_id] = asset
        return asset


@pytest.mark.asyncio
async def test_commons_client_parses_official_imageinfo_and_cc_by_rights() -> None:
    async with _client([_image_response()]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(query="NASA eclipse")
        )

    candidate = result.candidates[0]
    assert candidate.kind is CommonsMediaKind.IMAGE
    assert candidate.rights.license is CommonsLicense.CC_BY
    assert candidate.publish_eligible is True
    assert candidate.attribution.author == "NASA"
    assert str(candidate.direct_download_url).startswith("https://upload.wikimedia.org/")


@pytest.mark.asyncio
async def test_commons_search_skips_unsupported_items_without_hiding_exact_failure() -> None:
    mixed = _image_response()
    pages = mixed["query"]["pages"]  # type: ignore[index]
    pages.append(  # type: ignore[union-attr]
        {
            "pageid": 999,
            "title": "File:Unsupported document.pdf",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/unsupported.pdf",
                    "mime": "application/pdf",
                    "size": 123,
                    "width": 612,
                    "height": 792,
                    "sha1": "f" * 40,
                    "extmetadata": {},
                }
            ],
        }
    )
    async with _client([mixed]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(query="mixed media")
        )
    assert [candidate.page_id for candidate in result.candidates] == [123]

    exact = {
        "query": {
            "pages": [
                {
                    "pageid": 999,
                    "title": "File:Unsupported document.pdf",
                    "imageinfo": pages[1]["imageinfo"],  # type: ignore[index]
                }
            ]
        }
    }
    async with _client([exact]) as http_client:
        with pytest.raises(WikimediaCommonsError, match="neither a supported image nor video"):
            await _commons_client(http_client).discover(
                CommonsDiscoveryRequest(file_title="File:Unsupported document.pdf")
            )


@pytest.mark.asyncio
async def test_commons_client_parses_videoinfo_derivatives_from_official_upload_host() -> None:
    async with _client([_video_response(), _video_info_response()]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(file_title="File:Moon transit.webm")
        )

    candidate = result.candidates[0]
    assert candidate.kind is CommonsMediaKind.VIDEO
    assert candidate.duration_ms == 4250
    assert candidate.rights.license is CommonsLicense.PUBLIC_DOMAIN
    assert candidate.video_derivatives[0].mime_type == "video/mp4"
    assert candidate.publish_eligible is True


@pytest.mark.asyncio
async def test_commons_client_accepts_real_timed_ogg_video_metadata() -> None:
    image = _video_response()
    info = image["query"]["pages"][0]["imageinfo"][0]  # type: ignore[index]
    image["query"]["pages"][0]["pageid"] = 4250664  # type: ignore[index]
    image["query"]["pages"][0]["title"] = "File:Moon transit of sun large.ogv"  # type: ignore[index]
    info.update(  # type: ignore[union-attr]
        {
            "mime": "application/ogg",
            "size": 8078924,
            "sha1": "a21de698b16e94e58861336b33f324c26e3693da",
        }
    )
    video = _video_info_response()
    entry = video["query"]["pages"][0]  # type: ignore[index]
    entry["pageid"] = 4250664
    entry["title"] = "File:Moon transit of sun large.ogv"
    entry["videoinfo"][0].update({"mime": "video/ogg", "duration": 7.933})  # type: ignore[index]
    async with _client([image, video]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(file_title="File:Moon transit of sun large.ogv")
        )
    candidate = result.candidates[0]
    assert candidate.kind is CommonsMediaKind.VIDEO
    assert candidate.mime_type == "video/ogg"
    assert candidate.duration_ms == 7933


@pytest.mark.parametrize(
    ("license_name", "expected"),
    [
        ("Public domain", CommonsLicense.PUBLIC_DOMAIN),
        ("CC0 1.0", CommonsLicense.CC0),
        ("CC BY 4.0", CommonsLicense.CC_BY),
        ("CC BY-SA 4.0", CommonsLicense.CC_BY_SA),
        ("CC BY-NC 4.0", CommonsLicense.UNKNOWN),
        ("CC BY-ND 4.0", CommonsLicense.UNKNOWN),
        ("All rights reserved", CommonsLicense.UNKNOWN),
    ],
)
@pytest.mark.asyncio
async def test_commons_license_allowlist_fails_closed(
    license_name: str, expected: CommonsLicense
) -> None:
    async with _client([_image_response(license_name=license_name)]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(query="solar eclipse")
        )

    rights = result.candidates[0].rights
    assert rights.license is expected
    if expected is CommonsLicense.UNKNOWN:
        assert rights.requires_human_review is True
        assert rights.allows_commercial_use is False
        assert rights.allows_derivatives is False
    else:
        assert rights.allows_commercial_use is True
        assert rights.allows_derivatives is True


def test_client_request_cannot_supply_url_or_license_and_candidate_validates_type() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CommonsDiscoveryRequest.model_validate(
            {
                "query": "eclipse",
                "direct_download_url": "https://attacker.example/video.mp4",
                "license": "public_domain",
            }
        )
    with pytest.raises(ValidationError, match="video candidate must have a video MIME type"):
        CommonsVisualCandidate.model_validate(
            {
                "file_title": "File:wrong.jpg",
                "page_id": 1,
                "canonical_page_url": "https://commons.wikimedia.org/wiki/File:wrong.jpg",
                "direct_download_url": "https://upload.wikimedia.org/wrong.jpg",
                "kind": "video",
                "mime_type": "image/jpeg",
                "width": 1,
                "height": 1,
                "duration_ms": 1,
                "size_bytes": 1,
                "sha1": "c" * 40,
                "attribution": {"attribution_text": "x"},
                "rights": {
                    "license": "public_domain",
                    "allows_commercial_use": True,
                    "allows_derivatives": True,
                    "requires_attribution": False,
                    "requires_human_review": False,
                },
            }
        )
    with pytest.raises(ValidationError, match="unknown Commons rights"):
        CommonsRights(
            license=CommonsLicense.UNKNOWN,
            allows_commercial_use=True,
            allows_derivatives=True,
            requires_attribution=True,
            requires_human_review=False,
        )


@pytest.mark.asyncio
async def test_commons_search_skips_non_official_upload_urls_but_exact_lookup_fails() -> None:
    malicious = _image_response()
    info = malicious["query"]["pages"][0]["imageinfo"][0]  # type: ignore[index]
    info["url"] = "https://example.invalid/not-a-commons-file.jpg"  # type: ignore[index]
    async with _client([malicious]) as http_client:
        result = await _commons_client(http_client).discover(
            CommonsDiscoveryRequest(query="eclipse")
        )

    assert result.candidates == []

    async with _client([malicious]) as http_client:
        with pytest.raises(WikimediaCommonsError, match="non-official upload URL"):
            await _commons_client(http_client).discover(
                CommonsDiscoveryRequest(file_title="File:fixture.jpg")
            )


@pytest.mark.asyncio
async def test_stage_approve_reject_and_stale_revision_are_server_enforced(tmp_path) -> None:
    story = make_story()
    translation, script, _audio = make_artifacts()
    story = transition_story(story, StoryStatus.TRANSLATED, translation=translation)
    story = transition_story(story, StoryStatus.PENDING_FIRST_REVIEW)
    story = transition_story(story, StoryStatus.PROCESSING_SCRIPT)
    story = transition_story(story, StoryStatus.SCRIPT_READY, script=script)
    stories = InMemoryStoryRepository()
    await stories.create(story)
    candidate = CommonsVisualCandidate(
        file_title="File:fixture.jpg",
        page_id=71,
        canonical_page_url="https://commons.wikimedia.org/wiki/File:fixture.jpg",
        direct_download_url="https://upload.wikimedia.org/fixture.jpg",
        kind=CommonsMediaKind.IMAGE,
        mime_type="image/jpeg",
        width=1,
        height=1,
        size_bytes=len(_MINIMAL_JPEG),
        sha1=hashlib.sha1(_MINIMAL_JPEG).hexdigest(),
        attribution={"attribution_text": "Fixture author"},
        rights={
            "license": "public_domain",
            "allows_commercial_use": True,
            "allows_derivatives": True,
            "requires_attribution": False,
            "requires_human_review": False,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "upload.wikimedia.org"
        assert request.headers["api-user-agent"] == "test-agent/1.0 (contact: test)"
        return httpx.Response(
            200,
            content=_MINIMAL_JPEG,
            headers={"content-length": str(len(_MINIMAL_JPEG))},
            request=request,
        )

    repository = _DiscoveryRepository()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = VisualDiscoveryApplication(
            stories=stories,
            discovery=_OneCandidateDiscovery(candidate),
            repository=repository,
            store=LocalVisualDiscoveryStore(tmp_path, max_download_bytes=1_000),
            client=client,
            download_user_agent="test-agent/1.0 (contact: test)",
            max_download_bytes=1_000,
        )
        staged = await service.stage(
            StageCommonsVisualRequest(
                file_title="File:fixture.jpg",
                story_id=story.story_id,
                segment_id=script.segments[0].segment_id,
                expected_story_version=story.version,
                expected_script_revision=script.revision,
            )
        )
        assert staged.status is VisualDiscoveryStatus.STAGED
        assert staged.sha256 is not None
        mismatched_service = VisualDiscoveryApplication(
            stories=stories,
            discovery=_OneCandidateDiscovery(
                candidate.model_copy(update={"sha1": "d" * 40})
            ),
            repository=repository,
            store=LocalVisualDiscoveryStore(tmp_path, max_download_bytes=1_000),
            client=client,
            download_user_agent="test-agent/1.0 (contact: test)",
            max_download_bytes=1_000,
        )
        with pytest.raises(ValueError, match="provider SHA-1"):
            await mismatched_service.stage(
                StageCommonsVisualRequest(
                    file_title="File:fixture.jpg",
                    story_id=story.story_id,
                    segment_id=script.segments[0].segment_id,
                    expected_story_version=story.version,
                    expected_script_revision=script.revision,
                )
            )
        approved = await service.approve(
            staged.asset_id,
            VisualDiscoveryReviewRequest(expected_story_version=story.version, note="verified"),
        )
        assert approved.status is VisualDiscoveryStatus.APPROVED
        rejected = await service.reject(
            staged.asset_id,
            VisualDiscoveryReviewRequest(expected_story_version=story.version, note="withdrawn"),
        )
        assert rejected.status is VisualDiscoveryStatus.REJECTED
        stories._stories[story.story_id] = story.model_copy(
            update={"script": script.model_copy(update={"revision": script.revision + 1})}
        )
        with pytest.raises(StoryInvariantError, match="stale script revision"):
            await service.approve(
                staged.asset_id,
                VisualDiscoveryReviewRequest(expected_story_version=story.version),
            )
