import {SceneModuleRegistry, TemplateRegistry} from '../templates/registry';
import {worldWarmthTemplate} from '../templates/world-warmth';
import {EvidenceFullscreenScene} from './EvidenceFullscreenScene';
import {
  HostEvidenceFullBleedScene,
  HostEvidenceSplitScene,
} from './HostEvidenceScene';
import {SourceVideoScene} from './SourceVideoScene';
import type {EpisodeSceneRendererProps} from './types';

const sceneRegistry = new SceneModuleRegistry([
  {
    moduleId: 'host_evidence',
    variants: {
      host_split_editorial: HostEvidenceSplitScene,
      host_corner_full_bleed: HostEvidenceFullBleedScene,
    },
  },
  {
    moduleId: 'evidence_fullscreen',
    variants: {evidence_documentary: EvidenceFullscreenScene},
  },
  {
    moduleId: 'source_video',
    variants: {source_video_clean: SourceVideoScene},
  },
]);
export const templateRegistry = new TemplateRegistry(
  [worldWarmthTemplate],
  sceneRegistry,
);
export const registeredEpisodeSceneModules = Object.freeze(
  sceneRegistry.moduleIds(),
);

export const renderEpisodeScene = (sceneProps: EpisodeSceneRendererProps) => {
  const template = sceneProps.props.template;
  if (!template) {
    throw new Error('Production scenes require a versioned template snapshot.');
  }
  templateRegistry.resolve(template.template_id, template.template_version);
  const {scene} = sceneProps.track;
  const variantId =
    scene.variant_id ?? template.default_scene_variants[scene.module_id];
  if (!variantId) {
    throw new Error(`Template has no default variant for ${scene.module_id}.`);
  }
  const Scene = sceneRegistry.resolve(
    sceneProps.props,
    scene.module_id,
    variantId,
  );
  return <Scene {...sceneProps} />;
};

export type {EpisodeSceneRendererProps} from './types';
