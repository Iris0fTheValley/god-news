import {Composition} from 'remotion';

import {
  COMPOSITION_ID,
  VIDEO_FPS,
  VIDEO_HEIGHT,
  VIDEO_WIDTH,
} from './constants';
import {GodNewsShortVideo} from './GodNewsShortVideo';
import {buildRenderPlan} from './render-plan';
import {sampleProps} from './sample-props';
import {
  GodNewsVideoPropsSchema,
  parseGodNewsVideoProps,
  type GodNewsVideoProps,
} from './schema';

export const RemotionRoot = () => (
  <Composition
    id={COMPOSITION_ID}
    component={GodNewsShortVideo}
    width={VIDEO_WIDTH}
    height={VIDEO_HEIGHT}
    fps={VIDEO_FPS}
    durationInFrames={buildRenderPlan(sampleProps, VIDEO_FPS).durationInFrames}
    defaultProps={sampleProps}
    schema={GodNewsVideoPropsSchema}
    calculateMetadata={({props}: {props: GodNewsVideoProps}) => {
      const validated = parseGodNewsVideoProps(props);
      return {
        durationInFrames: buildRenderPlan(validated, VIDEO_FPS).durationInFrames,
        props: validated,
      };
    }}
  />
);
