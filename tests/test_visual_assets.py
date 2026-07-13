from __future__ import annotations

from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from god_news.api.app import create_app
from god_news.application.visual_assets import VisualAssetService
from god_news.domain.enums import ReviewDecision, SourceKind, StoryStatus
from god_news.domain.fsm import transition_story
from god_news.domain.models import (
    FirstReviewSubmission,
    IngestRequest,
    ScriptReviewSubmission,
    SourceSnapshot,
    TextSource,
    utc_now,
)
from god_news.domain.visual_assets import (
    ImageContentType,
    StoredVisualAsset,
    UploadSegmentVisualAssetRequest,
    VisualAssetOrigin,
)
from god_news.errors import ConcurrentWriteError, VisualAssetNotFoundError, VisualAssetUploadError
from god_news.infrastructure.database import Database
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.infrastructure.testing import InMemoryStoryRepository
from god_news.infrastructure.visual_asset_store import LocalVisualAssetStore
from god_news.infrastructure.visual_repository import SqlAlchemyVisualAssetRepository

from .conftest import Stack
from .test_fsm import make_artifacts, make_story

_MINIMAL_JPEG = (
    b"\xff\xd8"
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    b"\xff\xd9"
)


async def _body(payload: bytes) -> AsyncIterable[bytes]:
    yield payload


@dataclass
class InMemoryVisualAssetRepository:
    """Version-aware fake that mirrors the production mutation contract."""

    stories: InMemoryStoryRepository
    assets: dict[UUID, StoredVisualAsset] = field(default_factory=dict)

    async def list_for_script(
        self,
        story_id: UUID,
        *,
        script_revision: int,
    ) -> Sequence[StoredVisualAsset]:
        return [
            asset
            for asset in self.assets.values()
            if asset.story_id == story_id
            and (
                asset.origin is VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT
                or asset.script_revision == script_revision
            )
        ]

    async def get(self, story_id: UUID, asset_id: UUID) -> StoredVisualAsset:
        asset = self.assets.get(asset_id)
        if asset is None or asset.story_id != story_id:
            raise VisualAssetNotFoundError(story_id)
        return asset

    async def replace_segment_upload(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        replaced = next(
            (
                existing
                for existing in self.assets.values()
                if existing.story_id == asset.story_id
                and existing.segment_id == asset.segment_id
                and existing.script_revision == asset.script_revision
            ),
            None,
        )
        next_version = await self._advance(asset.story_id, expected_story_version)
        if replaced is not None:
            self.assets.pop(replaced.asset_id)
        self.assets[asset.asset_id] = asset
        return replaced, next_version

    async def delete_segment_upload(
        self,
        *,
        story_id: UUID,
        segment_id: UUID,
        script_revision: int,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        removed = next(
            (
                asset
                for asset in self.assets.values()
                if asset.story_id == story_id
                and asset.segment_id == segment_id
                and asset.script_revision == script_revision
                and asset.origin is VisualAssetOrigin.EDITOR_UPLOAD
            ),
            None,
        )
        if removed is None:
            return None, expected_story_version
        next_version = await self._advance(story_id, expected_story_version)
        self.assets.pop(removed.asset_id)
        return removed, next_version

    async def replace_source_screenshot(
        self,
        asset: StoredVisualAsset,
        *,
        expected_story_version: int,
    ) -> tuple[StoredVisualAsset | None, int]:
        replaced = next(
            (
                existing
                for existing in self.assets.values()
                if existing.story_id == asset.story_id
                and existing.origin is VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT
            ),
            None,
        )
        next_version = await self._advance(asset.story_id, expected_story_version)
        if replaced is not None:
            self.assets.pop(replaced.asset_id)
        self.assets[asset.asset_id] = asset
        return replaced, next_version

    async def _advance(self, story_id: UUID, expected_version: int) -> int:
        story = await self.stories.get(story_id)
        if story.version != expected_version:
            raise ConcurrentWriteError(story_id)
        saved = await self.stories.save(
            story.model_copy(update={"updated_at": utc_now()}),
            expected_version=expected_version,
        )
        return saved.version


async def _script_ready(stack: Stack):  # type: ignore[no-untyped-def]
    story = await stack.workflow.ingest(
        IngestRequest(
            source=TextSource(
                title="Visual asset fixture",
                language="en",
                text="A factual article used to exercise a visual-asset binding.",
            ),
            target_language="zh-CN",
            style="accurate narration",
            target_duration_seconds=60,
        )
    )
    return await stack.workflow.submit_first_review(
        story.story_id,
        FirstReviewSubmission(
            expected_story_version=story.version,
            decision=ReviewDecision.APPROVE,
            reviewer_id="visual-editor",
        ),
    )


@pytest.mark.asyncio
async def test_visual_asset_api_uses_real_bindings_and_never_invents_a_screenshot(
    stack: Stack,
    tmp_path: Path,
) -> None:
    ready = await _script_ready(stack)
    assert ready.status is StoryStatus.SCRIPT_READY
    assert ready.script is not None
    segment_id = ready.script.segments[0].segment_id
    repository = InMemoryVisualAssetRepository(stack.repository)
    stack.container.visual_assets = VisualAssetService(
        stories=stack.repository,
        repository=repository,
        store=LocalVisualAssetStore(
            tmp_path / "visual-assets",
            max_upload_bytes=1024,
            max_pixels=100,
        ),
    )

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            before = await client.get(f"/api/v1/stories/{ready.story_id}/visual-assets")
            assert before.status_code == 200
            assert before.json()["source_page_url"] is None
            assert before.json()["source_page_screenshot"] is None
            assert before.json()["segment_assets"] == []

            uploaded = await client.put(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{segment_id}",
                params={
                    "expected_story_version": ready.version,
                    "expected_script_revision": ready.script.revision,
                    "filename": "..\\unsafe.jpg",
                },
                content=_MINIMAL_JPEG,
                headers={"content-type": "image/jpeg"},
            )
            assert uploaded.status_code == 200
            first = uploaded.json()
            assert first["asset"]["origin"] == "editor_upload"
            assert first["asset"]["filename"] == "unsafe.jpg"
            assert first["story_version"] == ready.version + 1

            listed = await client.get(f"/api/v1/stories/{ready.story_id}/visual-assets")
            assert listed.status_code == 200
            assert listed.json()["story_version"] == ready.version + 1
            assert listed.json()["source_page_screenshot"] is None
            listed_asset_id = listed.json()["segment_assets"][0]["asset"]["asset_id"]
            assert listed_asset_id == first["asset"]["asset_id"]

            media = await client.get(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{first['asset']['asset_id']}/content"
            )
            assert media.status_code == 200
            assert media.headers["content-type"] == "image/jpeg"
            assert media.content == _MINIMAL_JPEG

            replacement = await client.put(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{segment_id}",
                params={
                    "expected_story_version": first["story_version"],
                    "expected_script_revision": ready.script.revision,
                    "filename": "replacement.jpg",
                },
                content=_MINIMAL_JPEG,
                headers={"content-type": "image/jpeg"},
            )
            assert replacement.status_code == 200
            assert replacement.json()["asset"]["asset_id"] != first["asset"]["asset_id"]
            stale_media = await client.get(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{first['asset']['asset_id']}/content"
            )
            assert stale_media.status_code == 404

            deleted = await client.delete(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{segment_id}",
                params={
                    "expected_story_version": replacement.json()["story_version"],
                    "expected_script_revision": ready.script.revision,
                },
            )
            assert deleted.status_code == 204
            after_delete = await client.get(f"/api/v1/stories/{ready.story_id}/visual-assets")
            assert after_delete.status_code == 200
            assert after_delete.json()["segment_assets"] == []


@pytest.mark.asyncio
async def test_visual_asset_api_rejects_bad_bytes_and_post_script_review_edits(
    stack: Stack,
    tmp_path: Path,
) -> None:
    ready = await _script_ready(stack)
    assert ready.script is not None
    segment_id = ready.script.segments[0].segment_id
    repository = InMemoryVisualAssetRepository(stack.repository)
    stack.container.visual_assets = VisualAssetService(
        stories=stack.repository,
        repository=repository,
        store=LocalVisualAssetStore(
            tmp_path / "visual-assets",
            max_upload_bytes=1024,
            max_pixels=100,
        ),
    )

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.put(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{segment_id}",
                params={
                    "expected_story_version": ready.version,
                    "expected_script_revision": ready.script.revision,
                    "filename": "not-an-image.png",
                },
                content=_MINIMAL_JPEG,
                headers={"content-type": "image/png"},
            )
            assert bad.status_code == 422
            assert bad.json()["code"] == "visual_asset_rejected"

            pending = await stack.workflow.submit_script_review(
                ready.story_id,
                # The failed upload has not bumped the story version.
                ScriptReviewSubmission(
                    expected_story_version=ready.version,
                    decision=ReviewDecision.APPROVE,
                    reviewer_id="script-editor",
                ),
            )
            assert pending.status is StoryStatus.PENDING_TTS
            immutable = await client.put(
                f"/api/v1/stories/{ready.story_id}/visual-assets/{segment_id}",
                params={
                    "expected_story_version": pending.version,
                    "expected_script_revision": ready.script.revision,
                    "filename": "later.jpg",
                },
                content=_MINIMAL_JPEG,
                headers={"content-type": "image/jpeg"},
            )
            assert immutable.status_code == 409
            assert immutable.json()["code"] == "story_invariant_violated"


@pytest.mark.asyncio
async def test_source_screenshot_is_shown_only_after_internal_capture_registration(
    stack: Stack,
    tmp_path: Path,
) -> None:
    ready = await _script_ready(stack)
    assert ready.script is not None
    source = SourceSnapshot(
        kind=SourceKind.URL,
        source_uri="https://news.example.com/article",
        final_uri="https://news.example.com/article",
        title=ready.source.title,
        fetcher="fixture",
        content_sha256=ready.source.content_sha256,
    )
    url_story = await stack.repository.save(
        ready.model_copy(update={"source": source, "updated_at": utc_now()}),
        expected_version=ready.version,
    )
    repository = InMemoryVisualAssetRepository(stack.repository)
    service = VisualAssetService(
        stories=stack.repository,
        repository=repository,
        store=LocalVisualAssetStore(
            tmp_path / "visual-assets",
            max_upload_bytes=1024,
            max_pixels=100,
        ),
    )

    before = await service.list(url_story.story_id)
    assert before.source_page_url == "https://news.example.com/article"
    assert before.source_page_screenshot is None

    registered = await service.register_source_screenshot(
        story_id=url_story.story_id,
        expected_story_version=url_story.version,
        filename="captured.jpg",
        declared_content_type="image/jpeg",
        body=_body(_MINIMAL_JPEG),
    )
    after = await service.list(url_story.story_id)
    assert after.source_page_screenshot is not None
    assert after.source_page_screenshot.asset_id == registered.asset.asset_id
    assert after.source_page_screenshot.origin is VisualAssetOrigin.SOURCE_PAGE_SCREENSHOT


@pytest.mark.asyncio
async def test_sqlite_visual_bindings_are_revision_scoped_and_bump_story_version(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'visuals.db').as_posix()}")
    await database.create_schema()
    stories = SqlAlchemyStoryRepository(database.sessions)
    visuals = SqlAlchemyVisualAssetRepository(
        database.sessions,
        storage_root=tmp_path / "outputs" / "visual-assets",
    )
    try:
        translation, script, _ = make_artifacts()
        ready = await stories.create(
            make_story().model_copy(
                update={
                    "status": StoryStatus.SCRIPT_READY,
                    "translation": translation,
                    "script": script,
                }
            )
        )

        first = StoredVisualAsset(
            story_id=ready.story_id,
            segment_id=script.segments[0].segment_id,
            script_revision=script.revision,
            origin=VisualAssetOrigin.EDITOR_UPLOAD,
            content_type="image/jpeg",
            filename="first.jpg",
            storage_key=f"{ready.story_id}/first.jpg",
            sha256="a" * 64,
            size_bytes=4,
        )
        replaced, next_version = await visuals.replace_segment_upload(
            first,
            expected_story_version=ready.version,
        )
        assert replaced is None
        assert next_version == ready.version + 1
        assert (await stories.get(ready.story_id)).version == next_version

        second = first.model_copy(
            update={
                "asset_id": uuid4(),
                "storage_key": f"{ready.story_id}/second.jpg",
                "filename": "second.jpg",
            }
        )
        with pytest.raises(ConcurrentWriteError):
            await visuals.replace_segment_upload(second, expected_story_version=ready.version)

        replaced, latest_version = await visuals.replace_segment_upload(
            second,
            expected_story_version=next_version,
        )
        assert replaced is not None
        assert replaced.asset_id == first.asset_id
        assert latest_version == next_version + 1
        assert [asset.storage_key for asset in await visuals.list_for_script(
            ready.story_id,
            script_revision=script.revision,
        )] == [second.storage_key]
        assert await visuals.protected_asset_paths() == [
            (tmp_path / "outputs" / "visual-assets" / second.storage_key).resolve()
        ]

        current = await stories.get(ready.story_id)
        archived = await stories.save(
            transition_story(
                current,
                StoryStatus.ARCHIVED,
            ),
            expected_version=current.version,
        )
        assert archived.status is StoryStatus.ARCHIVED
        assert await visuals.protected_asset_paths() == []
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_historical_script_revision_asset_is_not_served(
    stack: Stack,
    tmp_path: Path,
) -> None:
    ready = await _script_ready(stack)
    assert ready.script is not None
    repository = InMemoryVisualAssetRepository(stack.repository)
    service = VisualAssetService(
        stories=stack.repository,
        repository=repository,
        store=LocalVisualAssetStore(
            tmp_path / "visual-assets",
            max_upload_bytes=1024,
            max_pixels=100,
        ),
    )
    uploaded = await service.upload_segment(
        story_id=ready.story_id,
        segment_id=ready.script.segments[0].segment_id,
        request=UploadSegmentVisualAssetRequest(
            expected_story_version=ready.version,
            expected_script_revision=ready.script.revision,
            filename="current.jpg",
        ),
        declared_content_type="image/jpeg",
        body=_body(_MINIMAL_JPEG),
    )
    current = await stack.repository.get(ready.story_id)
    revised = current.script.model_copy(update={"revision": current.script.revision + 1})
    await stack.repository.save(
        current.model_copy(update={"script": revised, "updated_at": utc_now()}),
        expected_version=current.version,
    )
    with pytest.raises(VisualAssetNotFoundError):
        await service.media_path(ready.story_id, uploaded.asset.asset_id)


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + (b"\0" * 4)

    header = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", b"\0")
        + chunk(b"IEND", b"")
    )


def _jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        + b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        + b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
        + b"\xff\xd9"
    )


def _webp_lossless(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    frame = b"\x2f" + bits.to_bytes(4, "little")
    chunk = b"VP8L" + len(frame).to_bytes(4, "little") + frame + b"\0"
    body = b"WEBP" + chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "payload"),
    [
        (ImageContentType.PNG, _png(3, 2)),
        (ImageContentType.JPEG, _jpeg(3, 2)),
        (ImageContentType.WEBP, _webp_lossless(3, 2)),
    ],
)
async def test_visual_store_rejects_raster_pixel_bombs(
    tmp_path: Path,
    content_type: ImageContentType,
    payload: bytes,
) -> None:
    store = LocalVisualAssetStore(
        tmp_path / "visual-assets",
        max_upload_bytes=1024,
        max_pixels=4,
    )
    with pytest.raises(VisualAssetUploadError, match="pixel limit"):
        await store.write(
            story_id=uuid4(),
            asset_id=uuid4(),
            content_type=content_type,
            body=_body(payload),
        )
