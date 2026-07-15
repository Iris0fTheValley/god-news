import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

import type {SegmentTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

export const EvidenceFullscreenScene = ({
  props,
  track,
  segmentCount,
}: {
  props: GodNewsVideoProps;
  track: SegmentTrack;
  segmentCount: number;
}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const horizontal = width > height;
  const {segment} = track;
  const reveal = interpolate(frame, [0, 10], [0.96, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const caption =
    segment.captions.find((item) => item.kind === 'translation')?.text ??
    segment.spoken_text;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 20%, ${props.theme.accent}24, transparent 45%), ${props.theme.background}`,
        color: props.theme.foreground,
        fontFamily,
        padding: horizontal ? '44px 64px 48px' : '72px 58px 94px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          color: props.theme.accent,
          fontFamily: monoFamily,
          fontSize: horizontal ? 18 : 22,
          letterSpacing: 2,
        }}
      >
        <span>GOD NEWS / SOURCE EVIDENCE</span>
        <span>
          {String(segment.sequence + 1).padStart(2, '0')} /{' '}
          {String(segmentCount).padStart(2, '0')}
        </span>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          marginTop: horizontal ? 26 : 38,
          border: `2px solid ${props.theme.accent}66`,
          borderRadius: horizontal ? 34 : 30,
          overflow: 'hidden',
          position: 'relative',
          transform: `scale(${reveal})`,
          background:
            'linear-gradient(145deg, rgba(133,167,125,0.16), rgba(0,0,0,0.18))',
          boxShadow: `0 28px 90px ${props.theme.background}`,
        }}
      >
        <AbsoluteFill
          style={{
            justifyContent: 'center',
            padding: horizontal ? '70px 92px' : '78px 62px',
          }}
        >
          <div
            style={{
              color: props.theme.signal,
              fontFamily: monoFamily,
              fontSize: horizontal ? 20 : 23,
              letterSpacing: 3,
            }}
          >
            REVIEWED EVIDENCE SLOT / SWAPPABLE ASSET RENDERER
          </div>
          <div
            style={{
              color: '#d7ded3',
              fontSize: horizontal ? 48 : 46,
              lineHeight: 1.35,
              marginTop: horizontal ? 30 : 38,
              maxWidth: horizontal ? 1500 : 870,
            }}
          >
            {segment.visual_hint ?? 'Use the reviewed source evidence for this story.'}
          </div>
          <div
            style={{
              color: '#a8b4a8',
              fontFamily: monoFamily,
              fontSize: horizontal ? 16 : 19,
              letterSpacing: 1.5,
              marginTop: 34,
            }}
          >
            HOST HIDDEN / SPEAKER {segment.speaker_id} / EMOTION {segment.emotion}
          </div>
        </AbsoluteFill>
      </div>

      <div
        style={{
          borderTop: `1px solid ${props.theme.accent}55`,
          fontSize: horizontal ? 38 : 48,
          fontWeight: 650,
          lineHeight: 1.32,
          marginTop: horizontal ? 26 : 36,
          paddingTop: horizontal ? 20 : 26,
          textAlign: 'center',
          textWrap: 'balance',
        }}
      >
        {caption}
      </div>
      <div
        style={{
          backgroundColor: '#2d342e',
          borderRadius: 999,
          height: 5,
          marginTop: horizontal ? 20 : 26,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            backgroundColor: props.theme.signal,
            height: '100%',
            width: `${Math.min(100, (frame / track.durationInFrames) * 100)}%`,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
