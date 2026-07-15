import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

import type {GodNewsVideoProps} from '../schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

export const TitleCard = ({
  title,
  subtitle,
  theme,
}: Pick<GodNewsVideoProps, 'title' | 'subtitle' | 'theme'>) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const horizontal = width > height;
  const opacity = interpolate(frame, [0, Math.max(1, fps * 0.35)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const shift = interpolate(frame, [0, fps * 0.55], [40, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 82% 18%, ${theme.accent}33, transparent 34%), ${theme.background}`,
        color: theme.foreground,
        fontFamily,
        padding: horizontal ? '78px 110px' : '150px 82px',
        justifyContent: 'center',
      }}
    >
      <div style={{opacity, transform: `translateY(${shift}px)`, maxWidth: horizontal ? 1320 : 880}}>
        <div
          style={{
            fontFamily: monoFamily,
            fontSize: horizontal ? 26 : 29,
            letterSpacing: horizontal ? 9 : 7,
            color: theme.accent,
            marginBottom: horizontal ? 34 : 48,
          }}
        >
          GOD NEWS / GLOBAL GOOD NEWS
        </div>
        <div
          style={{
            fontSize: horizontal ? 88 : 82,
            fontWeight: 760,
            lineHeight: 1.1,
            textWrap: 'balance',
          }}
        >
          {title}
        </div>
        {subtitle ? (
          <div
            style={{
              fontFamily: monoFamily,
              fontSize: horizontal ? 25 : 27,
              letterSpacing: 3,
              marginTop: 34,
              color: '#a8aaa2',
            }}
          >
            {subtitle}
          </div>
        ) : null}
      </div>
      <div
        style={{
          position: 'absolute',
          right: horizontal ? 100 : 72,
          bottom: horizontal ? 72 : 118,
          width: horizontal ? 280 : 230,
          height: 6,
          borderRadius: 999,
          background: `linear-gradient(90deg, ${theme.signal}, ${theme.accent})`,
        }}
      />
    </AbsoluteFill>
  );
};
