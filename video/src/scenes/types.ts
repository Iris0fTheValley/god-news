import type {SceneTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';

export type EpisodeSceneRendererProps = Readonly<{
  props: GodNewsVideoProps;
  track: SceneTrack;
  segmentCount: number;
}>;
