import type {
  EpisodeScene,
  GodNewsVideoProps,
  OutputProfile,
  SceneVariantDefinition,
  TemplateDefinition,
} from '../schema';

export type Rect = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
}>;

export type CompiledSceneLayout = Readonly<{
  safeArea: Rect;
  media: Rect;
  host: Rect | null;
  caption: Rect;
  source: Rect;
  mediaFit: 'contain' | 'cover';
  variant: SceneVariantDefinition;
}>;

const rectWithin = (outer: Rect, inner: Rect): boolean =>
  inner.x >= outer.x &&
  inner.y >= outer.y &&
  inner.width > 0 &&
  inner.height > 0 &&
  inner.x + inner.width <= outer.x + outer.width + Number.EPSILON &&
  inner.y + inner.height <= outer.y + outer.height + Number.EPSILON;

export const assertCompiledLayout = (layout: CompiledSceneLayout): void => {
  const canvas: Rect = {x: 0, y: 0, width: 1, height: 1};
  if (!rectWithin(canvas, layout.safeArea)) {
    throw new Error('Compiled safe area escapes the output canvas.');
  }
  for (const [name, rect] of [
    ['media', layout.media],
    ['caption', layout.caption],
    ['source', layout.source],
  ] as const) {
    if (!rectWithin(layout.safeArea, rect)) {
      throw new Error(`Compiled ${name} region escapes the template safe area.`);
    }
  }
  if (layout.host && !rectWithin(layout.safeArea, layout.host)) {
    throw new Error('Compiled host region escapes the template safe area.');
  }
};

const requireProfile = (
  props: GodNewsVideoProps,
): OutputProfile => {
  const profile = props.output_profiles.find(
    (candidate) =>
      candidate.profile_id === props.runtime_assets.output_profile_id,
  );
  if (!profile) throw new Error('Active output profile is not declared.');
  return profile;
};

const requireTemplate = (props: GodNewsVideoProps): TemplateDefinition => {
  if (!props.template) {
    throw new Error('Versioned template snapshot is required for this scene.');
  }
  return props.template;
};

const requireVariant = (
  template: TemplateDefinition,
  scene: EpisodeScene,
): SceneVariantDefinition => {
  const variantId =
    scene.variant_id ?? template.default_scene_variants[scene.module_id];
  const variant = template.scene_variants.find(
    (candidate) => candidate.variant_id === variantId,
  );
  if (!variant || variant.module_id !== scene.module_id) {
    throw new Error(
      `Template ${template.template_id}@${template.template_version} does not register ` +
        `${scene.module_id}/${variantId ?? '<missing>'}.`,
    );
  }
  return variant;
};

export const compileSceneLayout = (
  props: GodNewsVideoProps,
  scene: EpisodeScene,
): CompiledSceneLayout => {
  const profile = requireProfile(props);
  const template = requireTemplate(props);
  const layout = template.layout_preset.profiles.find(
    (candidate) => candidate.profile_id === profile.profile_id,
  );
  if (!layout) {
    throw new Error(
      `Template ${template.template_id}@${template.template_version} has no ` +
        `${profile.profile_id} layout.`,
    );
  }
  const variant = requireVariant(template, scene);
  if (!variant.supported_profiles.includes(profile.profile_id)) {
    throw new Error(
      `Scene variant ${variant.variant_id} does not support ${profile.profile_id}.`,
    );
  }
  if (
    scene.host_visibility === 'visible' &&
    (!scene.host_slot || !variant.supported_host_slots.includes(scene.host_slot))
  ) {
    throw new Error(
      `Scene variant ${variant.variant_id} does not support host slot ` +
        `${scene.host_slot ?? '<missing>'}.`,
    );
  }
  if (scene.host_visibility === 'hidden' && scene.host_slot !== null) {
    throw new Error('A hidden host scene cannot retain a host slot.');
  }

  const safeArea: Rect = {
    x: layout.safe_area_left,
    y: layout.safe_area_top,
    width: 1 - layout.safe_area_left - layout.safe_area_right,
    height: 1 - layout.safe_area_top - layout.safe_area_bottom,
  };
  const horizontal = profile.layout === 'horizontal';
  const captionHeight = horizontal ? 0.2 : 0.23;
  const sourceHeight = horizontal ? 0.055 : 0.045;
  const contentHeight = safeArea.height - captionHeight - sourceHeight;
  const cornerHost = scene.host_slot === 'corner';
  const hostWidth = cornerHost
    ? layout.host_corner_width
    : layout.host_primary_width;
  const host: Rect | null =
    scene.host_visibility === 'visible'
      ? cornerHost
        ? {
            x: safeArea.x + safeArea.width - hostWidth,
            y: safeArea.y + contentHeight * 0.08,
            width: hostWidth,
            height: contentHeight * (horizontal ? 0.72 : 0.48),
          }
        : horizontal
          ? {
              x: safeArea.x,
              y: safeArea.y,
              width: hostWidth,
              height: contentHeight,
            }
          : {
              x: safeArea.x,
              y: safeArea.y + contentHeight * 0.62,
              width: safeArea.width,
              height: contentHeight * 0.38,
            }
      : null;
  const media: Rect =
    scene.host_visibility === 'visible' && !cornerHost
      ? horizontal
        ? {
            x: safeArea.x + hostWidth + 0.018,
            y: safeArea.y,
            width: safeArea.width - hostWidth - 0.018,
            height: contentHeight,
          }
        : {
            x: safeArea.x,
            y: safeArea.y,
            width: safeArea.width,
            height: contentHeight * 0.59,
          }
      : {
          x: safeArea.x,
          y: safeArea.y,
          width: safeArea.width,
          height: contentHeight,
        };
  const compiled: CompiledSceneLayout = {
    safeArea,
    media,
    host,
    caption: {
      x: safeArea.x + (safeArea.width * (1 - layout.caption_max_width)) / 2,
      y: safeArea.y + contentHeight + sourceHeight,
      width: safeArea.width * layout.caption_max_width,
      height: captionHeight,
    },
    source: {
      x: media.x,
      y: safeArea.y + contentHeight,
      width: media.width,
      height: sourceHeight,
    },
    mediaFit: layout.media_fit,
    variant,
  };
  assertCompiledLayout(compiled);
  return compiled;
};

export const rectStyle = (
  rect: Rect,
): Readonly<Record<'left' | 'top' | 'width' | 'height', string>> => ({
  left: `${rect.x * 100}%`,
  top: `${rect.y * 100}%`,
  width: `${rect.width * 100}%`,
  height: `${rect.height * 100}%`,
});
