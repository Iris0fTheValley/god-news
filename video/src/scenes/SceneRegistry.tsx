import type {ComponentType} from 'react';

import type {SceneTrack} from '../render-plan';
import type {EpisodeSceneModule, GodNewsVideoProps} from '../schema';
import {EvidenceFullscreenScene} from './EvidenceFullscreenScene';
import {HostEvidenceScene} from './HostEvidenceScene';
import {SourceVideoScene} from './SourceVideoScene';

export type EpisodeSceneRendererProps = Readonly<{
  props: GodNewsVideoProps;
  track: SceneTrack;
  segmentCount: number;
}>;

const sceneRegistry = {
  host_evidence: HostEvidenceScene,
  evidence_fullscreen: EvidenceFullscreenScene,
  source_video: SourceVideoScene,
} satisfies Record<EpisodeSceneModule, ComponentType<EpisodeSceneRendererProps>>;

export const registeredEpisodeSceneModules = Object.freeze(
  Object.keys(sceneRegistry) as EpisodeSceneModule[],
);

export const renderEpisodeScene = (sceneProps: EpisodeSceneRendererProps) => {
  const Scene = sceneRegistry[sceneProps.track.scene.module_id];
  return <Scene {...sceneProps} />;
};
