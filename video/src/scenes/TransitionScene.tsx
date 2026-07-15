import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';

import type {SceneTransition, VideoTheme} from '../schema';

export const TransitionScene = ({
  type,
  theme,
  durationInFrames,
}: {
  type: SceneTransition;
  theme: VideoTheme;
  durationInFrames: number;
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  if (type === 'black') {
    return <AbsoluteFill style={{backgroundColor: '#000'}} />;
  }
  const translate = type === 'slide' ? `${(1 - progress) * 100}%` : '0%';
  const scaleX = type === 'wipe' ? progress : 1;
  const opacity = type === 'crossfade' ? Math.sin(progress * Math.PI) : 1;
  const background =
    type === 'mood_shift'
      ? `radial-gradient(circle at ${20 + progress * 60}% 50%, ${theme.signal}, ${theme.background} 58%)`
      : `linear-gradient(110deg, ${theme.background}, ${theme.accent}, ${theme.background})`;
  return (
    <AbsoluteFill style={{backgroundColor: theme.background, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          background,
          opacity,
          transform: `translateX(${translate}) scaleX(${scaleX})`,
          transformOrigin: 'left center',
        }}
      />
    </AbsoluteFill>
  );
};
