from __future__ import annotations

from collections.abc import Iterable

from god_news.domain.video import (
    DesignTokens,
    EpisodeHostSlot,
    EpisodeSceneModule,
    LayoutPreset,
    OutputProfileLayout,
    SceneVariantDefinition,
    TemplateAssetRequirement,
    TemplateCapabilities,
    TemplateDefinition,
    VideoOutputProfileId,
    VisualAssetType,
)


def world_warmth_template() -> TemplateDefinition:
    profiles = [
        VideoOutputProfileId.DOUYIN_VERTICAL,
        VideoOutputProfileId.BILIBILI_HORIZONTAL,
    ]
    return TemplateDefinition(
        template_id="world_warmth",
        template_version="1.0.0",
        display_name="World Warmth Editorial",
        capabilities=TemplateCapabilities(
            supported_profiles=profiles,
            supported_modules=[
                EpisodeSceneModule.HOST_EVIDENCE,
                EpisodeSceneModule.EVIDENCE_FULLSCREEN,
                EpisodeSceneModule.SOURCE_VIDEO,
            ],
        ),
        scene_variants=[
            SceneVariantDefinition(
                variant_id="host_split_editorial",
                module_id=EpisodeSceneModule.HOST_EVIDENCE,
                display_name="Host and editorial evidence split",
                supported_profiles=profiles,
                supported_host_slots=[
                    EpisodeHostSlot.PRIMARY,
                    EpisodeHostSlot.CORNER,
                ],
                asset_requirements=[
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.IMAGE,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.SOURCE_SCREENSHOT,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                ],
                minimum_visual_assets=1,
                maximum_visual_assets=1,
            ),
            SceneVariantDefinition(
                variant_id="host_corner_full_bleed",
                module_id=EpisodeSceneModule.HOST_EVIDENCE,
                display_name="Full bleed evidence with corner host",
                supported_profiles=profiles,
                supported_host_slots=[EpisodeHostSlot.CORNER],
                asset_requirements=[
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.IMAGE,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.SOURCE_SCREENSHOT,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                ],
                minimum_visual_assets=1,
                maximum_visual_assets=1,
            ),
            SceneVariantDefinition(
                variant_id="evidence_documentary",
                module_id=EpisodeSceneModule.EVIDENCE_FULLSCREEN,
                display_name="Documentary full-screen evidence",
                supported_profiles=profiles,
                asset_requirements=[
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.IMAGE,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                    TemplateAssetRequirement(
                        asset_type=VisualAssetType.SOURCE_SCREENSHOT,
                        required=False,
                        minimum=0,
                        maximum=1,
                    ),
                ],
                minimum_visual_assets=1,
                maximum_visual_assets=1,
            ),
            SceneVariantDefinition(
                variant_id="source_video_clean",
                module_id=EpisodeSceneModule.SOURCE_VIDEO,
                display_name="Clean reviewed source video",
                supported_profiles=profiles,
            ),
        ],
        default_scene_variants={
            EpisodeSceneModule.HOST_EVIDENCE: "host_split_editorial",
            EpisodeSceneModule.EVIDENCE_FULLSCREEN: "evidence_documentary",
            EpisodeSceneModule.SOURCE_VIDEO: "source_video_clean",
        },
        layout_preset=LayoutPreset(
            preset_id="world_warmth_responsive",
            profiles=[
                OutputProfileLayout(
                    profile_id=VideoOutputProfileId.DOUYIN_VERTICAL,
                    safe_area_top=0.045,
                    safe_area_right=0.055,
                    safe_area_bottom=0.11,
                    safe_area_left=0.055,
                    host_primary_width=0.58,
                    host_corner_width=0.38,
                    caption_max_width=0.9,
                    media_fit="cover",
                ),
                OutputProfileLayout(
                    profile_id=VideoOutputProfileId.BILIBILI_HORIZONTAL,
                    safe_area_top=0.045,
                    safe_area_right=0.04,
                    safe_area_bottom=0.075,
                    safe_area_left=0.04,
                    host_primary_width=0.32,
                    host_corner_width=0.22,
                    caption_max_width=0.78,
                    media_fit="cover",
                ),
            ],
        ),
        design_tokens=DesignTokens(caption_max_lines=3),
        intro_variant="world_warmth_intro",
        outro_variant="world_warmth_outro",
        transition_pack="soft_editorial",
        caption_preset="bilingual_editorial",
        source_bar_preset="verified_source",
        host_preset="restrained_presenter",
    )


class TemplateRegistry:
    """Immutable template catalog with fail-fast identity validation."""

    def __init__(self, definitions: Iterable[TemplateDefinition]) -> None:
        entries: dict[tuple[str, str], TemplateDefinition] = {}
        for definition in definitions:
            key = (definition.template_id, definition.template_version)
            if key in entries:
                raise ValueError(
                    f"duplicate video template registration: {definition.template_id}@"
                    f"{definition.template_version}"
                )
            entries[key] = definition
        if not entries:
            raise ValueError("video template registry cannot be empty")
        self._entries = entries

    def resolve(self, template_id: str, template_version: str) -> TemplateDefinition:
        try:
            return self._entries[(template_id, template_version)]
        except KeyError as exc:
            raise ValueError(
                f"video template is not registered: {template_id}@{template_version}"
            ) from exc

    def list(self) -> tuple[TemplateDefinition, ...]:
        return tuple(
            self._entries[key]
            for key in sorted(self._entries, key=lambda item: (item[0], item[1]))
        )


def create_default_template_registry() -> TemplateRegistry:
    return TemplateRegistry([world_warmth_template()])
