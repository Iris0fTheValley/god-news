import {AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig} from 'remotion';

import {sourceForBrowser} from '../browser-assets';
import type {SceneTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';

const fontFamily =
  'Inter, "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", sans-serif';
const monoFamily = '"IBM Plex Mono", Consolas, monospace';

export const SourceVideoScene = ({
  props,
  track,
}: {
  props: GodNewsVideoProps;
  track: SceneTrack;
  segmentCount: number;
}) => {
  if (track.kind !== 'source_video') {
    throw new Error('source_video requires an approved source-video track');
  }
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const horizontal = width > height;
  const source = sourceForBrowser(track.asset.local_path);
  if (!source) {
    throw new Error('Approved source video was not staged for browser rendering.');
  }
  const sourceTimeMs = track.asset.in_ms + Math.round((frame / fps) * 1000);
  const cue = track.asset.captions.find(
    (candidate) =>
      candidate.start_ms <= sourceTimeMs && sourceTimeMs < candidate.end_ms,
  );
  const caption =
    cue?.captions.find((item) => item.kind === 'translation')?.text ??
    cue?.captions.find((item) => item.kind === 'verbatim')?.text;
  const startFrom = Math.round((track.asset.in_ms / 1000) * fps);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#050705',
        color: props.theme.foreground,
        fontFamily,
        overflow: 'hidden',
      }}
    >
      <OffthreadVideo
        src={source}
        startFrom={startFrom}
        muted={track.asset.audio_mode === 'muted'}
        style={{width: '100%', height: '100%', objectFit: 'contain'}}
      />
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(180deg, rgba(0,0,0,0.42) 0%, transparent 20%, transparent 66%, rgba(0,0,0,0.82) 100%)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: horizontal ? 54 : 42,
          right: horizontal ? 54 : 42,
          top: horizontal ? 38 : 62,
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: monoFamily,
          fontSize: horizontal ? 17 : 21,
          letterSpacing: 2,
          color: props.theme.accent,
        }}
      >
        <span>ORIGINAL SOURCE VIDEO / REVIEWED TRANSCRIPT</span>
        <span>{track.asset.source_label}</span>
      </div>
      {caption ? (
        <div
          style={{
            position: 'absolute',
            left: horizontal ? '12%' : '8%',
            right: horizontal ? '12%' : '8%',
            bottom: horizontal ? 58 : 126,
            padding: horizontal ? '18px 28px' : '24px 30px',
            borderRadius: 18,
            backgroundColor: 'rgba(4, 7, 5, 0.82)',
            border: `1px solid ${props.theme.accent}66`,
            fontSize: horizontal ? 36 : 47,
            fontWeight: 650,
            lineHeight: 1.32,
            textAlign: 'center',
            textWrap: 'balance',
          }}
        >
          {caption}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
