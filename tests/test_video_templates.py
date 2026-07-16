from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from god_news.domain.enums import CaptionKind, SceneTransition, SpeechEmotion
from god_news.domain.models import (
    CaptionVariant,
    ProductionManifest,
    TimelineSegment,
)
from god_news.domain.video import (
    EpisodeHostSlot,
    EpisodeHostVisibility,
    EpisodePlan,
    EpisodeScene,
    EpisodeSceneModule,
    RemotionVideoProps,
    VisualAssetType,
    VisualRenderAsset,
)
from god_news.domain.video_templates import (
    TemplateRegistry,
    create_default_template_registry,
    world_warmth_template,
)


def _manifest(batch_id, segment_id) -> ProductionManifest:
    return ProductionManifest(
        story_id=batch_id,
        script_revision=1,
        spoken_language="en-US",
        total_duration_ms=1_000,
        timeline=[
            TimelineSegment(
                segment_id=segment_id,
                sequence=0,
                start_ms=0,
                end_ms=1_000,
                spoken_text="A library reopened.",
                spoken_language="en-US",
                captions=[
                    CaptionVariant(
                        language="en-US",
                        kind=CaptionKind.VERBATIM,
                        text="A library reopened.",
                    ),
                    CaptionVariant(
                        language="zh-CN",
                        kind=CaptionKind.TRANSLATION,
                        text="图书馆重新开放。",
                    )
                ],
                speaker_id="anchor",
                emotion=SpeechEmotion.HAPPINESS,
                scene_transition=SceneTransition.CROSSFADE,
                audio_path=str(Path.cwd() / "segment.wav"),
            )
        ],
    )


def test_default_template_registry_is_versioned_and_complete() -> None:
    registry = create_default_template_registry()
    template = registry.resolve("world_warmth", "1.0.0")

    assert template.template_id == "world_warmth"
    assert template.template_version == "1.0.0"
    assert set(template.default_scene_variants) == set(
        template.capabilities.supported_modules
    )
    assert {
        variant.variant_id for variant in template.scene_variants
    } >= {
        "host_split_editorial",
        "host_corner_full_bleed",
        "evidence_documentary",
        "source_video_clean",
    }


def test_template_registry_rejects_duplicate_identity() -> None:
    template = world_warmth_template()

    with pytest.raises(ValueError, match="duplicate video template"):
        TemplateRegistry([template, template])


def test_template_visual_asset_count_is_enforced_before_render() -> None:
    batch_id = uuid4()
    segment_id = uuid4()
    scene = EpisodeScene(
        sequence=0,
        module_id=EpisodeSceneModule.HOST_EVIDENCE,
        narration_segment_id=segment_id,
        speaker_id="anchor",
        host_visibility=EpisodeHostVisibility.VISIBLE,
        host_slot=EpisodeHostSlot.PRIMARY,
        transition_type=SceneTransition.CROSSFADE,
        variant_id="host_split_editorial",
        visual_asset_ids=[],
    )

    with pytest.raises(ValidationError, match="visual asset count"):
        RemotionVideoProps(
            manifest=_manifest(batch_id, segment_id),
            title="Good news",
            episode_plan=EpisodePlan(batch_id=batch_id, scenes=[scene]),
            template=world_warmth_template(),
        )


def test_template_accepts_one_reviewed_image_for_host_scene(tmp_path) -> None:
    batch_id = uuid4()
    story_id = uuid4()
    segment_id = uuid4()
    asset_id = uuid4()
    image = tmp_path / "evidence.png"
    image.write_bytes(b"png-evidence")
    asset = VisualRenderAsset(
        asset_id=asset_id,
        story_id=story_id,
        segment_id=segment_id,
        asset_type=VisualAssetType.IMAGE,
        content_type="image/png",
        filename="evidence.png",
        local_path=str(image),
        sha256="a" * 64,
        size_bytes=image.stat().st_size,
        width=640,
        height=360,
        source_label="Reviewed fixture",
    )
    scene = EpisodeScene(
        sequence=0,
        module_id=EpisodeSceneModule.HOST_EVIDENCE,
        narration_segment_id=segment_id,
        speaker_id="anchor",
        host_visibility=EpisodeHostVisibility.VISIBLE,
        host_slot=EpisodeHostSlot.PRIMARY,
        transition_type=SceneTransition.CROSSFADE,
        variant_id="host_split_editorial",
        visual_asset_ids=[asset_id],
        primary_visual_asset_id=asset_id,
    )

    props = RemotionVideoProps(
        manifest=_manifest(batch_id, segment_id),
        title="Good news",
        episode_plan=EpisodePlan(batch_id=batch_id, scenes=[scene]),
        visual_assets=[asset],
        template=world_warmth_template(),
    )

    assert props.template is not None
    assert props.episode_plan is not None
    assert props.episode_plan.scenes[0].primary_visual_asset_id == asset_id
