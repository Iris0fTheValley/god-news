import {AbsoluteFill, Audio, Sequence, useVideoConfig} from 'remotion';

import {sourceForBrowser} from './browser-assets';
import {buildRenderPlan} from './render-plan';
import type {GodNewsVideoProps} from './schema';
import {renderEpisodeScene} from './scenes/SceneRegistry';
import {resolveProgramPresentation} from './templates/presentation-registry';

export const GodNewsShortVideo = (props: GodNewsVideoProps) => {
  const {fps} = useVideoConfig();
  const plan = buildRenderPlan(props, fps);
  const presentation = resolveProgramPresentation(props);
  const segmentCount = props.manifest.timeline.length;
  const bgmSource = sourceForBrowser(
    props.runtime_assets.bgm_src ?? props.bgm?.local_path,
  );

  return (
    <AbsoluteFill style={{backgroundColor: props.theme.background}}>
      {plan.tracks.map((track) => {
        if (track.kind === 'intro') {
          return (
            <Sequence
              key="intro"
              from={track.from}
              durationInFrames={track.durationInFrames}
              name="Program title"
            >
              <presentation.Intro
                title={props.title}
                theme={props.theme}
                {...(props.subtitle ? {subtitle: props.subtitle} : {})}
              />
            </Sequence>
          );
        }
        if (track.kind === 'transition') {
          return (
            <Sequence
              key={`transition-${track.afterSceneId}`}
              from={track.from}
              durationInFrames={track.durationInFrames}
              name={`${track.transition_type} transition`}
            >
              <presentation.Transition track={track} theme={props.theme} />
            </Sequence>
          );
        }
        if (track.kind === 'outro') {
          return (
            <Sequence
              key="outro"
              from={track.from}
              durationInFrames={track.durationInFrames}
              name="Program closing"
            >
              <presentation.Outro
                title={props.title}
                theme={props.theme}
              />
            </Sequence>
          );
        }

        if (track.kind === 'source_video') {
          return (
            <Sequence
              key={track.scene.scene_id}
              from={track.from}
              durationInFrames={track.durationInFrames}
              name="Reviewed source video"
            >
              {renderEpisodeScene({props, track, segmentCount})}
            </Sequence>
          );
        }

        const audioSource = sourceForBrowser(
          props.runtime_assets.audio_by_segment_id[track.segment.segment_id] ??
            track.segment.audio_path,
        );
        return (
          <Sequence
            key={track.segment.segment_id}
            from={track.from}
            durationInFrames={track.durationInFrames}
            name={`Story segment ${track.segment.sequence + 1}`}
          >
            {renderEpisodeScene({props, track, segmentCount})}
            {audioSource ? <Audio src={audioSource} /> : null}
          </Sequence>
        );
      })}
      {bgmSource && props.bgm ? (
        <Sequence from={0} durationInFrames={plan.durationInFrames} name="Local BGM">
          <Audio src={bgmSource} volume={props.bgm.volume} loop={props.bgm.loop} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
