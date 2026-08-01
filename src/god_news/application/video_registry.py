from __future__ import annotations

from collections import defaultdict

from god_news.domain.video import (
    EpisodeHostSlot,
    EpisodeSceneModule,
    SceneVariantDefinition,
    TemplateDefinition,
    VideoOutputProfileId,
)
from god_news.domain.video_ports import VideoBatchRepository
from god_news.domain.video_registry import (
    SetVideoCapabilityPolicy,
    VideoCapabilityKind,
    VideoCapabilityPolicy,
    VideoCapabilityView,
    VideoRegistryView,
)
from god_news.domain.video_registry_ports import VideoCapabilityPolicyRepository
from god_news.domain.video_templates import TemplateRegistry
from god_news.errors import (
    VideoCapabilityConflictError,
    VideoCapabilityNotFoundError,
)


def template_key(template: TemplateDefinition) -> str:
    return f"template:{template.template_id}@{template.template_version}"


def module_key(module: EpisodeSceneModule) -> str:
    return f"module:{module.value}"


def variant_key(template: TemplateDefinition, variant: SceneVariantDefinition) -> str:
    return (
        f"variant:{template.template_id}@{template.template_version}:"
        f"{variant.variant_id}"
    )


def preset_key(kind: str, preset_id: str) -> str:
    return f"preset:{kind}@{preset_id}"


class VideoRegistryService:
    """Operational policy overlay for immutable production definitions."""

    def __init__(
        self,
        *,
        templates: TemplateRegistry,
        policies: VideoCapabilityPolicyRepository,
        batches: VideoBatchRepository,
    ) -> None:
        self._templates = templates
        self._policies = policies
        self._batches = batches

    async def view(self) -> VideoRegistryView:
        definitions = self._templates.list()
        stored = await self._policies.list()
        policies: dict[str, VideoCapabilityPolicy] = {}

        def policy(key: str) -> VideoCapabilityPolicy:
            result = stored.get(key, VideoCapabilityPolicy(key=key))
            policies[key] = result
            return result

        dependencies: dict[str, list[str]] = defaultdict(list)
        used_by: dict[str, list[str]] = defaultdict(list)
        metadata: dict[
            str,
            tuple[
                VideoCapabilityKind,
                str,
                bool,
                list[VideoOutputProfileId],
                list[EpisodeHostSlot],
            ],
        ] = {}
        for template in definitions:
            t_key = template_key(template)
            metadata[t_key] = (
                VideoCapabilityKind.TEMPLATE,
                template.display_name,
                True,
                list(template.capabilities.supported_profiles),
                [],
            )
            for module in template.capabilities.supported_modules:
                m_key = module_key(module)
                metadata.setdefault(
                    m_key,
                    (
                        VideoCapabilityKind.MODULE,
                        module.value.replace("_", " ").title(),
                        True,
                        list(template.capabilities.supported_profiles),
                        [],
                    ),
                )
                dependencies[t_key].append(m_key)
                used_by[m_key].append(t_key)
            for variant in template.scene_variants:
                v_key = variant_key(template, variant)
                m_key = module_key(variant.module_id)
                metadata[v_key] = (
                    VideoCapabilityKind.VARIANT,
                    variant.display_name,
                    True,
                    list(variant.supported_profiles),
                    list(variant.supported_host_slots),
                )
                dependencies[v_key].append(m_key)
                used_by[m_key].append(v_key)
                used_by[v_key].append(t_key)
                if template.default_scene_variants[variant.module_id] == variant.variant_id:
                    dependencies[t_key].append(v_key)
            for kind, value in self._template_presets(template):
                p_key = preset_key(kind, value)
                metadata.setdefault(
                    p_key,
                    (
                        VideoCapabilityKind.PRESET,
                        value.replace("_", " ").title(),
                        False,
                        list(template.capabilities.supported_profiles),
                        [],
                    ),
                )
                dependencies[t_key].append(p_key)
                used_by[p_key].append(t_key)

        batch_usage: dict[str, list[str]] = defaultdict(list)
        for batch in await self._batches.list(limit=200, offset=0):
            if batch.template is not None:
                batch_usage[template_key(batch.template)].append(str(batch.batch_id))
            props = batch.remotion_props
            plan = props.episode_plan if props is not None else None
            if plan is None:
                continue
            for scene in plan.scenes:
                batch_usage[module_key(scene.module_id)].append(str(batch.batch_id))
                if batch.template is not None and scene.variant_id is not None:
                    matched_variant = next(
                        (
                            item
                            for item in batch.template.scene_variants
                            if item.variant_id == scene.variant_id
                        ),
                        None,
                    )
                    if matched_variant is not None:
                        batch_usage[variant_key(batch.template, matched_variant)].append(
                            str(batch.batch_id)
                        )

        effective: dict[str, bool] = {}

        def is_effective(key: str, trail: frozenset[str] = frozenset()) -> bool:
            if key in effective:
                return effective[key]
            if key in trail:
                return False
            current = policy(key).enabled_for_new_batches
            result = current and all(
                is_effective(item, trail | {key}) for item in dependencies.get(key, ())
            )
            effective[key] = result
            return result

        capabilities: list[VideoCapabilityView] = []
        for key in sorted(metadata):
            kind, display_name, configurable, profiles, host_slots = metadata[key]
            capability_policy = policy(key)
            disabled_by = [
                item
                for item in dependencies.get(key, ())
                if not is_effective(item)
            ]
            if not capability_policy.enabled_for_new_batches:
                disabled_by.insert(0, key)
            batch_ids = list(dict.fromkeys(batch_usage.get(key, ())))
            capabilities.append(
                VideoCapabilityView(
                    key=key,
                    kind=kind,
                    display_name=display_name,
                    configurable=configurable,
                    policy=capability_policy,
                    effective_enabled=is_effective(key),
                    disabled_by=disabled_by,
                    dependencies=list(dict.fromkeys(dependencies.get(key, ()))),
                    used_by=list(dict.fromkeys(used_by.get(key, ()))),
                    supported_profiles=profiles,
                    supported_host_slots=host_slots,
                    active_batch_ids=batch_ids[:20],
                    usage_count=len(batch_ids),
                )
            )
        return VideoRegistryView(capabilities=capabilities)

    async def set_policy(
        self,
        request: SetVideoCapabilityPolicy,
    ) -> VideoRegistryView:
        registry = await self.view()
        capability = next(
            (item for item in registry.capabilities if item.key == request.key),
            None,
        )
        if capability is None:
            raise VideoCapabilityNotFoundError()
        if not capability.configurable:
            raise VideoCapabilityConflictError(
                "Renderer presets are registered dependencies and cannot be disabled here."
            )
        if request.enabled_for_new_batches:
            blocking = [
                dependency
                for dependency in capability.dependencies
                if next(
                    (
                        item.effective_enabled
                        for item in registry.capabilities
                        if item.key == dependency
                    ),
                    False,
                )
                is False
            ]
            if blocking:
                raise VideoCapabilityConflictError(
                    "Capability dependencies must be enabled first: "
                    + ", ".join(blocking)
                )
        await self._policies.set(
            key=request.key,
            enabled_for_new_batches=request.enabled_for_new_batches,
            expected_version=request.expected_version,
            reason=request.reason,
            operator_id=request.operator_id,
        )
        return await self.view()

    async def resolve_template_for_new_batch(
        self,
        template_id: str,
        template_version: str,
    ) -> TemplateDefinition:
        template = self._templates.resolve(template_id, template_version)
        registry = await self.view()
        capability = next(
            (
                item
                for item in registry.capabilities
                if item.key == template_key(template)
            ),
            None,
        )
        if capability is None or not capability.effective_enabled:
            blockers = capability.disabled_by if capability is not None else []
            detail = f" Disabled by: {', '.join(blockers)}." if blockers else ""
            raise VideoCapabilityConflictError(
                "Video template is disabled for new batches." + detail
            )
        enabled_variants = [
            variant
            for variant in template.scene_variants
            if next(
                (
                    item.effective_enabled
                    for item in registry.capabilities
                    if item.key == variant_key(template, variant)
                ),
                False,
            )
        ]
        return template.model_copy(update={"scene_variants": enabled_variants})

    @staticmethod
    def _template_presets(template: TemplateDefinition) -> tuple[tuple[str, str], ...]:
        return (
            ("intro", template.intro_variant),
            ("outro", template.outro_variant),
            ("transition", template.transition_pack),
            ("caption", template.caption_preset),
            ("source-bar", template.source_bar_preset),
            ("host", template.host_preset),
            ("layout", template.layout_preset.preset_id),
        )
