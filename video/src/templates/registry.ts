import type {ComponentType} from 'react';

import type {EpisodeSceneRendererProps} from '../scenes/types';
import type {
  EpisodeSceneModule,
  GodNewsVideoProps,
  SceneVariantDefinition,
  TemplateDefinition,
} from '../schema';
import {
  captionPresetRegistry,
  hostPresetRegistry,
  introRegistry,
  outroRegistry,
  sourceBarPresetRegistry,
  transitionRegistry,
} from './presentation-registry';

export type SceneVariantRenderer = ComponentType<EpisodeSceneRendererProps>;

export type SceneModuleDefinition = Readonly<{
  moduleId: EpisodeSceneModule;
  variants: Readonly<Record<string, SceneVariantRenderer>>;
}>;

export class SceneModuleRegistry {
  readonly #modules: ReadonlyMap<EpisodeSceneModule, SceneModuleDefinition>;

  constructor(definitions: readonly SceneModuleDefinition[]) {
    const modules = new Map<EpisodeSceneModule, SceneModuleDefinition>();
    for (const definition of definitions) {
      if (modules.has(definition.moduleId)) {
        throw new Error(`Duplicate scene module registration: ${definition.moduleId}`);
      }
      const variantIds = Object.keys(definition.variants);
      if (variantIds.length === 0 || new Set(variantIds).size !== variantIds.length) {
        throw new Error(`Scene module ${definition.moduleId} has invalid variants.`);
      }
      modules.set(definition.moduleId, definition);
    }
    this.#modules = modules;
  }

  resolve(
    props: GodNewsVideoProps,
    moduleId: EpisodeSceneModule,
    variantId: string,
  ): SceneVariantRenderer {
    const definition = this.#modules.get(moduleId);
    const renderer = definition?.variants[variantId];
    if (!renderer) {
      throw new Error(`Scene renderer is not registered: ${moduleId}/${variantId}`);
    }
    this.validateTemplateVariant(props, moduleId, variantId);
    return renderer;
  }

  has(moduleId: EpisodeSceneModule, variantId: string): boolean {
    return this.#modules.get(moduleId)?.variants[variantId] !== undefined;
  }

  moduleIds(): readonly EpisodeSceneModule[] {
    return [...this.#modules.keys()];
  }

  private validateTemplateVariant(
    props: GodNewsVideoProps,
    moduleId: EpisodeSceneModule,
    variantId: string,
  ): void {
    const template = props.template;
    if (!template) throw new Error('Versioned template snapshot is missing.');
    const variant: SceneVariantDefinition | undefined =
      template.scene_variants.find((candidate) => candidate.variant_id === variantId);
    if (!variant || variant.module_id !== moduleId) {
      throw new Error(
        `Template ${template.template_id}@${template.template_version} does not own ` +
          `${moduleId}/${variantId}.`,
      );
    }
  }
}

export class TemplateRegistry {
  readonly #templates: ReadonlyMap<string, TemplateDefinition>;

  constructor(
    definitions: readonly TemplateDefinition[],
    sceneModules: SceneModuleRegistry,
  ) {
    const templates = new Map<string, TemplateDefinition>();
    for (const definition of definitions) {
      const key = `${definition.template_id}@${definition.template_version}`;
      if (templates.has(key)) {
        throw new Error(`Duplicate template registration: ${key}`);
      }
      for (const variant of definition.scene_variants) {
        if (!sceneModules.has(variant.module_id, variant.variant_id)) {
          throw new Error(
            `Template ${key} references an unregistered scene variant: ` +
              `${variant.module_id}/${variant.variant_id}`,
          );
        }
      }
      if (!introRegistry.has(definition.intro_variant)) {
        throw new Error(`Template ${key} references an unregistered intro variant.`);
      }
      if (!outroRegistry.has(definition.outro_variant)) {
        throw new Error(`Template ${key} references an unregistered outro variant.`);
      }
      if (!transitionRegistry.has(definition.transition_pack)) {
        throw new Error(`Template ${key} references an unregistered transition pack.`);
      }
      if (!captionPresetRegistry.has(definition.caption_preset)) {
        throw new Error(`Template ${key} references an unregistered caption preset.`);
      }
      if (!sourceBarPresetRegistry.has(definition.source_bar_preset)) {
        throw new Error(`Template ${key} references an unregistered source bar preset.`);
      }
      if (!hostPresetRegistry.has(definition.host_preset)) {
        throw new Error(`Template ${key} references an unregistered host preset.`);
      }
      templates.set(key, definition);
    }
    if (templates.size === 0) throw new Error('Template registry cannot be empty.');
    this.#templates = templates;
  }

  resolve(templateId: string, templateVersion: string): TemplateDefinition {
    const key = `${templateId}@${templateVersion}`;
    const template = this.#templates.get(key);
    if (!template) throw new Error(`Template is not registered: ${key}`);
    return template;
  }

  list(): readonly TemplateDefinition[] {
    return [...this.#templates.values()];
  }
}
