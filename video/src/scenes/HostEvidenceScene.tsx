import type {CSSProperties} from 'react';
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  Video,
} from 'remotion';

import {sourceForBrowser} from '../browser-assets';
import type {SceneTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

const HostSilhouette = ({accent}: {accent: string}) => (
  <div
    style={{
      position: 'relative',
      width: '100%',
      height: '100%',
      minHeight: 220,
      overflow: 'hidden',
      borderRadius: 30,
      background: `radial-gradient(circle at 50% 24%, ${accent}3d, transparent 25%), linear-gradient(160deg, ${accent}1c, #090c0a)`,
    }}
  >
    <div
      style={{
        position: 'absolute',
        width: '25%',
        aspectRatio: '1',
        borderRadius: '50%',
        background: `linear-gradient(145deg, ${accent}, #d9e3d5)`,
        left: '37.5%',
        top: '16%',
        boxShadow: `0 0 60px ${accent}44`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        width: '58%',
        height: '54%',
        borderRadius: '48% 48% 12% 12%',
        background: `linear-gradient(150deg, ${accent}bb, #27322a)`,
        left: '21%',
        bottom: '-9%',
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 24,
        bottom: 20,
        color: '#dfe8dc',
        fontFamily: monoFamily,
        fontSize: 16,
        letterSpacing: 2,
      }}
    >
      HOST SLOT / SWAPPABLE
    </div>
  </div>
);

export const HostEvidenceScene = ({
  props,
  track,
  segmentCount,
}: {
  props: GodNewsVideoProps;
  track: SceneTrack;
  segmentCount: number;
}) => {
  if (track.kind !== 'segment') {
    throw new Error('host_evidence requires a narration segment track');
  }
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const horizontal = width > height;
  const captionEntrance = interpolate(frame, [0, 10], [28, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const captionOpacity = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const {segment} = track;
  const hostSource = sourceForBrowser(
    props.runtime_assets.host_video_by_segment_id[segment.segment_id],
  );
  const cornerHost = track.scene.host_slot === 'corner';
  const enterProgress = track.scene.host_enter
    ? interpolate(frame, [0, 10], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 1;
  const exitStart = Math.max(0, track.durationInFrames - 9);
  const exitProgress = track.scene.host_exit
    ? interpolate(frame, [exitStart, Math.max(exitStart + 1, track.durationInFrames - 1)], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 1;
  const hostOpacity = Math.min(enterProgress, exitProgress);
  const hostShift = (1 - enterProgress) * (horizontal ? -34 : 34) +
    (1 - exitProgress) * (horizontal ? -28 : 28);
  const rootStyle: CSSProperties = {
    background: `radial-gradient(circle at 86% 10%, ${props.theme.accent}22, transparent 30%), ${props.theme.background}`,
    color: props.theme.foreground,
    fontFamily,
    padding: horizontal ? '46px 64px 50px' : '76px 64px 92px',
  };

  return (
    <AbsoluteFill style={rootStyle}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: monoFamily,
          fontSize: horizontal ? 18 : 22,
          letterSpacing: 2,
          color: props.theme.accent,
        }}
      >
        <span>GOD NEWS / VERIFIED STORY</span>
        <span>
          {String(segment.sequence + 1).padStart(2, '0')} /{' '}
          {String(segmentCount).padStart(2, '0')}
        </span>
      </div>

      <div
        style={{
          display: cornerHost ? 'block' : 'grid',
          gridTemplateColumns: horizontal
            ? 'minmax(280px, 0.34fr) minmax(0, 0.66fr)'
            : '1fr',
          gridTemplateRows: horizontal
            ? '1fr'
            : 'minmax(360px, 0.8fr) minmax(420px, 1fr)',
          gap: horizontal ? 34 : 30,
          marginTop: horizontal ? 30 : 42,
          minHeight: 0,
          flex: 1,
          position: 'relative',
        }}
      >
        <div
          style={{
            ...(cornerHost
              ? {
                  position: 'absolute',
                  right: horizontal ? 26 : 22,
                  top: horizontal ? 26 : 22,
                  width: horizontal ? '22%' : '42%',
                  height: horizontal ? '54%' : '34%',
                  zIndex: 2,
                }
              : {minHeight: 0}),
            opacity: hostOpacity,
            transform: `translateX(${hostShift}px)`,
          }}
        >
          {hostSource ? (
            <div
              style={{
                width: '100%',
                height: '100%',
                minHeight: 220,
                overflow: 'hidden',
                borderRadius: 30,
                background: `radial-gradient(circle at 50% 30%, ${props.theme.accent}28, transparent 58%)`,
              }}
            >
              <Video
                src={hostSource}
                muted
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                }}
              />
            </div>
          ) : (
            <HostSilhouette accent={props.theme.accent} />
          )}
        </div>
        <div
          style={{
            height: cornerHost ? '100%' : undefined,
            minHeight: 0,
            border: `2px solid ${props.theme.accent}55`,
            borderRadius: 30,
            padding: horizontal ? '38px 42px' : '34px 38px',
            display: 'flex',
            flexDirection: 'column',
            background: 'linear-gradient(145deg, rgba(133,167,125,0.12), rgba(0,0,0,0.08))',
          }}
        >
          <div
            style={{
              fontFamily: monoFamily,
              fontSize: horizontal ? 18 : 20,
              color: props.theme.signal,
              letterSpacing: 2,
            }}
          >
            EDITORIAL VISUAL BRIEF
          </div>
          <div
            style={{
              fontSize: horizontal ? 36 : 38,
              lineHeight: 1.35,
              color: '#cdd4c9',
              marginTop: horizontal ? 24 : 28,
            }}
          >
            {segment.visual_hint ?? 'Use the reviewed source evidence for this story.'}
          </div>
          <div
            style={{
              marginTop: 'auto',
              paddingTop: 24,
              display: 'flex',
              gap: 12,
              flexWrap: 'wrap',
              fontFamily: monoFamily,
              fontSize: horizontal ? 15 : 17,
              color: '#a8b4a8',
            }}
          >
            <span>SPEAKER / {segment.speaker_id}</span>
            <span>EMOTION / {segment.emotion}</span>
          </div>
        </div>
      </div>

      <div
        style={{
          marginTop: horizontal ? 28 : 38,
          transform: `translateY(${captionEntrance}px)`,
          opacity: captionOpacity,
          borderTop: `1px solid ${props.theme.accent}55`,
          paddingTop: horizontal ? 22 : 28,
          fontSize: horizontal ? 38 : 48,
          fontWeight: 650,
          lineHeight: 1.32,
          textAlign: 'center',
          textWrap: 'balance',
        }}
      >
        {segment.captions.find((caption) => caption.kind === 'translation')?.text ??
          segment.spoken_text}
      </div>
      <div
        style={{
          marginTop: horizontal ? 22 : 28,
          height: 5,
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
