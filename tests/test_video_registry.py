from __future__ import annotations

from pathlib import Path

import pytest

from god_news.application.video_registry import (
    VideoRegistryService,
    module_key,
    variant_key,
)
from god_news.domain.video import EpisodeSceneModule
from god_news.domain.video_registry import SetVideoCapabilityPolicy, VideoCapabilityKind
from god_news.domain.video_templates import create_default_template_registry
from god_news.errors import (
    ConcurrentVideoCapabilityWriteError,
    VideoCapabilityConflictError,
)
from god_news.infrastructure.database import Database
from god_news.infrastructure.video_registry_repository import (
    SqlAlchemyVideoCapabilityPolicyRepository,
)
from god_news.infrastructure.video_repository import SqlAlchemyVideoBatchRepository


@pytest.mark.asyncio
async def test_module_policy_blocks_only_new_batch_template_resolution(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'registry.db').as_posix()}")
    await database.create_schema()
    policies = SqlAlchemyVideoCapabilityPolicyRepository(database.sessions)
    service = VideoRegistryService(
        templates=create_default_template_registry(),
        policies=policies,
        batches=SqlAlchemyVideoBatchRepository(database.sessions),
    )
    key = module_key(EpisodeSceneModule.SOURCE_VIDEO)
    try:
        initial = await service.view()
        module = next(item for item in initial.capabilities if item.key == key)
        assert module.kind is VideoCapabilityKind.MODULE
        assert module.effective_enabled
        assert module.policy.version == 1

        disabled = await service.set_policy(
            SetVideoCapabilityPolicy(
                key=key,
                enabled_for_new_batches=False,
                expected_version=1,
                reason="Temporarily disable source-video scenes.",
                operator_id="test-operator",
            )
        )
        disabled_module = next(item for item in disabled.capabilities if item.key == key)
        template = next(
            item
            for item in disabled.capabilities
            if item.kind is VideoCapabilityKind.TEMPLATE
        )
        assert not disabled_module.effective_enabled
        assert disabled_module.policy.version == 2
        assert not template.effective_enabled
        assert key in template.disabled_by
        with pytest.raises(VideoCapabilityConflictError, match="disabled"):
            await service.resolve_template_for_new_batch("world_warmth", "1.1.0")

        with pytest.raises(ConcurrentVideoCapabilityWriteError):
            await service.set_policy(
                SetVideoCapabilityPolicy(
                    key=key,
                    enabled_for_new_batches=True,
                    expected_version=1,
                    reason="Stale writer must fail.",
                    operator_id="stale-operator",
                )
            )

        restored = await service.set_policy(
            SetVideoCapabilityPolicy(
                key=key,
                enabled_for_new_batches=True,
                expected_version=2,
                reason="Restore source-video production scenes.",
                operator_id="test-operator",
            )
        )
        assert next(
            item
            for item in restored.capabilities
            if item.kind is VideoCapabilityKind.TEMPLATE
        ).effective_enabled
        resolved = await service.resolve_template_for_new_batch("world_warmth", "1.1.0")
        assert resolved.template_id == "world_warmth"

        non_default = next(
            variant
            for variant in resolved.scene_variants
            if variant.variant_id == "host_only_editorial"
        )
        disabled_variant_key = variant_key(resolved, non_default)
        await service.set_policy(
            SetVideoCapabilityPolicy(
                key=disabled_variant_key,
                enabled_for_new_batches=False,
                expected_version=1,
                reason="Disable one optional scene composition.",
                operator_id="test-operator",
            )
        )
        filtered = await service.resolve_template_for_new_batch("world_warmth", "1.1.0")
        assert non_default.variant_id not in {
            variant.variant_id for variant in filtered.scene_variants
        }
        assert "host_split_editorial" in {
            variant.variant_id for variant in filtered.scene_variants
        }
    finally:
        await database.aclose()
