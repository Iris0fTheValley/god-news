from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from god_news.domain.media_catalog import (
    MediaCatalogLifecycle,
    MediaCatalogSourceKind,
    make_catalog_id,
)
from god_news.errors import (
    ConcurrentMediaCatalogWriteError,
    MediaCatalogConflictError,
)
from god_news.infrastructure.database import Database
from god_news.infrastructure.media_catalog_repository import (
    SqlAlchemyMediaCatalogRepository,
)
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.infrastructure.visual_repository import VisualAssetRow

from .test_fsm import make_story


@pytest.mark.asyncio
async def test_media_catalog_archive_restore_and_content_integrity(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'catalog.db').as_posix()}")
    await database.create_schema()
    stories = SqlAlchemyStoryRepository(database.sessions)
    visual_root = tmp_path / "visuals"
    discovery_root = tmp_path / "discovery"
    source_root = tmp_path / "source"
    repository = SqlAlchemyMediaCatalogRepository(
        database.sessions,
        visual_root=visual_root,
        discovery_root=discovery_root,
        source_media_root=source_root,
    )
    try:
        story = await stories.create(make_story())
        asset_id = uuid4()
        body = b"catalog-fixture"
        storage_key = f"{story.story_id}/{asset_id}.png"
        path = visual_root / storage_key
        path.parent.mkdir(parents=True)
        path.write_bytes(body)
        async with database.sessions() as session:
            assert isinstance(session, AsyncSession)
            async with session.begin():
                session.add(
                    VisualAssetRow(
                        asset_id=str(asset_id),
                        story_id=str(story.story_id),
                        segment_id=None,
                        script_revision=None,
                        origin="source_page_screenshot",
                        content_type="image/png",
                        filename="source.png",
                        storage_key=storage_key,
                        sha256=hashlib.sha256(body).hexdigest(),
                        size_bytes=len(body),
                        created_at=story.created_at,
                    )
                )

        catalog_id = make_catalog_id(MediaCatalogSourceKind.VISUAL_ASSET, asset_id)
        active = await repository.get_entry(catalog_id)
        assert active.lifecycle is MediaCatalogLifecycle.ACTIVE
        assert active.lifecycle_version == 1
        assert active.selectable

        archived = await repository.set_lifecycle(
            catalog_id,
            lifecycle=MediaCatalogLifecycle.ARCHIVED,
            expected_version=1,
            operator_id="test-operator",
            reason="Fixture lifecycle verification.",
        )
        assert archived.lifecycle is MediaCatalogLifecycle.ARCHIVED
        assert archived.lifecycle_version == 2
        assert not archived.selectable
        assert await repository.is_archived(
            MediaCatalogSourceKind.VISUAL_ASSET,
            asset_id,
        )

        with pytest.raises(ConcurrentMediaCatalogWriteError):
            await repository.set_lifecycle(
                catalog_id,
                lifecycle=MediaCatalogLifecycle.ACTIVE,
                expected_version=1,
                operator_id="stale-operator",
                reason="Stale restore must fail.",
            )

        restored = await repository.set_lifecycle(
            catalog_id,
            lifecycle=MediaCatalogLifecycle.ACTIVE,
            expected_version=2,
            operator_id="test-operator",
            reason="Restore verified fixture.",
        )
        assert restored.lifecycle is MediaCatalogLifecycle.ACTIVE
        assert restored.lifecycle_version == 3
        entry, resolved = await repository.resolve_content(catalog_id)
        assert entry.catalog_id == catalog_id
        assert resolved == path.resolve()

        await repository.set_lifecycle(
            catalog_id,
            lifecycle=MediaCatalogLifecycle.ARCHIVED,
            expected_version=3,
            operator_id="test-operator",
            reason="Prepare missing-file restore test.",
        )
        path.unlink()
        with pytest.raises(MediaCatalogConflictError, match="missing"):
            await repository.set_lifecycle(
                catalog_id,
                lifecycle=MediaCatalogLifecycle.ACTIVE,
                expected_version=4,
                operator_id="test-operator",
                reason="Missing bytes must prevent restore.",
            )
    finally:
        await database.aclose()
