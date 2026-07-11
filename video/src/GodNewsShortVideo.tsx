import type {CSSProperties, ReactNode} from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

import {buildRenderPlan, type SegmentTrack} from './render-plan';
import type {GodNewsVideoProps} from './schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

const sourceForBrowser = (source: string | undefined): string | null => {
  if (!source) return null;
  if (/^(https?:|data:|blob:)/u.test(source)) return source;
  if (/^[a-zA-Z]:[\\/]/u.test(source) || source.startsWith('\\\\')) {
    return null;
  }
  return staticFile(source.replace(/^[/\\]+/u, '').replaceAll('\\', '/'));
};

const BlackPlaceholder = ({children}: {children?: ReactNode}) => (
  <AbsoluteFill
    style={{
      backgroundColor: '#000000',
      color: '#f3f1e8',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily,
    }}
  >
    {children}
  </AbsoluteFill>
);

const Intro = ({title, subtitle}: Pick<GodNewsVideoProps, 'title' | 'subtitle'>) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const opacity = interpolate(frame, [0, Math.max(1, fps * 0.35)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <BlackPlaceholder>
      <div style={{opacity, width: 830, textAlign: 'left'}}>
        <div
          style={{
            fontFamily: monoFamily,
            fontSize: 29,
            letterSpacing: 8,
            color: '#85a77d',
            marginBottom: 44,
          }}
        >
          GOD NEWS / OPEN
        </div>
        <div style={{fontSize: 86, fontWeight: 760, lineHeight: 1.12}}>{title}</div>
        {subtitle ? (
          <div
            style={{
              fontFamily: monoFamily,
              fontSize: 27,
              letterSpacing: 3,
              marginTop: 36,
              color: '#a8aaa2',
            }}
          >
            {subtitle}
          </div>
        ) : null}
      </div>
    </BlackPlaceholder>
  );
};

const SegmentScene = ({
  props,
  track,
  segmentCount,
}: {
  props: GodNewsVideoProps;
  track: SegmentTrack;
  segmentCount: number;
}) => {
  const frame = useCurrentFrame();
  const entrance = interpolate(frame, [0, 8], [32, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = interpolate(frame, [0, 7], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const {segment} = track;
  const hasLive2D = Boolean(props.visual_reservations.live2d);
  const hasDifferentialArt = Boolean(
    props.visual_reservations.differential_art,
  );

  const rootStyle: CSSProperties = {
    backgroundColor: props.theme.background,
    color: props.theme.foreground,
    fontFamily,
    padding: '98px 82px 112px',
  };

  return (
    <AbsoluteFill style={rootStyle}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontFamily: monoFamily,
          fontSize: 25,
          letterSpacing: 2,
          color: props.theme.accent,
        }}
      >
        <span>GOD NEWS / STORY</span>
        <span>
          {String(segment.sequence + 1).padStart(2, '0')} /{' '}
          {String(segmentCount).padStart(2, '0')}
        </span>
      </div>

      <div
        style={{
          marginTop: 82,
          border: `2px solid ${props.theme.accent}55`,
          borderRadius: 34,
          height: 730,
          padding: 42,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          background:
            'linear-gradient(145deg, rgba(133,167,125,0.12), rgba(0,0,0,0.08))',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: monoFamily,
              fontSize: 23,
              color: props.theme.signal,
              letterSpacing: 2,
            }}
          >
            VISUAL PIPELINE / PLACEHOLDER
          </div>
          <div
            style={{
              fontSize: 44,
              lineHeight: 1.35,
              color: '#cdd4c9',
              marginTop: 36,
              maxWidth: 800,
            }}
          >
            {segment.visual_hint ?? 'No visual hint supplied'}
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 14,
            flexWrap: 'wrap',
            fontFamily: monoFamily,
            fontSize: 20,
          }}
        >
          <span style={{border: '1px solid #536054', borderRadius: 999, padding: '10px 18px'}}>
            LIVE2D {hasLive2D ? 'RESERVED' : 'EMPTY'}
          </span>
          <span style={{border: '1px solid #536054', borderRadius: 999, padding: '10px 18px'}}>
            DIFF-ART {hasDifferentialArt ? 'RESERVED' : 'EMPTY'}
          </span>
        </div>
      </div>

      <div
        style={{
          marginTop: 98,
          transform: `translateY(${entrance}px)`,
          opacity,
        }}
      >
        <div
          style={{
            display: 'flex',
            gap: 18,
            fontFamily: monoFamily,
            fontSize: 22,
            color: props.theme.accent,
            marginBottom: 32,
          }}
        >
          <span>SPEAKER / {segment.speaker_id}</span>
          <span>EMOTION / {segment.emotion}</span>
        </div>
        <div style={{fontSize: 60, fontWeight: 650, lineHeight: 1.42}}>
          {segment.text}
        </div>
      </div>

      <div
        style={{
          marginTop: 'auto',
          height: 6,
          backgroundColor: '#2d342e',
          overflow: 'hidden',
          borderRadius: 999,
        }}
      >
        <div
          style={{
            width: `${Math.min(100, (frame / track.durationInFrames) * 100)}%`,
            height: '100%',
            backgroundColor: props.theme.signal,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export const GodNewsShortVideo = (props: GodNewsVideoProps) => {
  const {fps} = useVideoConfig();
  const plan = buildRenderPlan(props, fps);
  const segmentCount = props.manifest.timeline.length;
  const bgmSource = sourceForBrowser(
    props.runtime_assets.bgm_src ?? props.bgm?.local_path,
  );

  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      {plan.tracks.map((track) => {
        if (track.kind === 'intro') {
          return (
            <Sequence
              key="intro"
              from={track.from}
              durationInFrames={track.durationInFrames}
              name="Black intro placeholder"
            >
              <Intro title={props.title} subtitle={props.subtitle} />
            </Sequence>
          );
        }
        if (track.kind === 'transition') {
          return (
            <Sequence
              key={`transition-${track.afterSegmentId}`}
              from={track.from}
              durationInFrames={track.durationInFrames}
              name="Black transition placeholder"
            >
              <BlackPlaceholder />
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
            name={`Segment ${track.segment.sequence + 1}`}
          >
            <SegmentScene
              props={props}
              track={track}
              segmentCount={segmentCount}
            />
            {audioSource ? <Audio src={audioSource} /> : null}
          </Sequence>
        );
      })}
      {bgmSource && props.bgm ? (
        <Sequence from={0} durationInFrames={plan.durationInFrames} name="Local BGM">
          <Audio
            src={bgmSource}
            volume={props.bgm.volume}
            loop={props.bgm.loop}
          />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
