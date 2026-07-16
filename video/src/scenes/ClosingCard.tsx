import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

import type {GodNewsVideoProps} from '../schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

export const ClosingCard = ({
  title,
  theme,
}: Pick<GodNewsVideoProps, 'title' | 'theme'>) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const horizontal = width > height;
  const opacity = interpolate(frame, [0, Math.max(1, fps * 0.45)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const scale = interpolate(frame, [0, Math.max(1, fps * 0.7)], [0.97, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 18% 82%, ${theme.signal}24, transparent 30%), radial-gradient(circle at 82% 18%, ${theme.accent}2e, transparent 36%), ${theme.background}`,
        color: theme.foreground,
        fontFamily,
        padding: horizontal ? '88px 112px' : '160px 82px',
        justifyContent: 'center',
        alignItems: 'center',
        textAlign: 'center',
      }}
    >
      <div style={{opacity, transform: `scale(${scale})`, maxWidth: horizontal ? 1260 : 850}}>
        <div
          style={{
            fontFamily: monoFamily,
            color: theme.accent,
            fontSize: horizontal ? 25 : 28,
            letterSpacing: horizontal ? 8 : 6,
            marginBottom: horizontal ? 34 : 46,
          }}
        >
          GOD NEWS / EPISODE ARCHIVED
        </div>
        <div
          style={{
            fontSize: horizontal ? 82 : 76,
            fontWeight: 780,
            lineHeight: 1.12,
          }}
        >
          本期好消息已归档
        </div>
        <div
          style={{
            marginTop: horizontal ? 30 : 40,
            fontSize: horizontal ? 30 : 32,
            lineHeight: 1.4,
            color: '#c9cbc3',
          }}
        >
          {title}
        </div>
        <div
          style={{
            marginTop: horizontal ? 42 : 54,
            fontFamily: monoFamily,
            fontSize: horizontal ? 22 : 25,
            letterSpacing: 4,
            color: theme.signal,
          }}
        >
          SOURCES PRESERVED · SEE YOU NEXT TIME
        </div>
      </div>
    </AbsoluteFill>
  );
};
