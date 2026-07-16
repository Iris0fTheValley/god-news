import {AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig} from 'remotion';

import {sourceForBrowser} from '../browser-assets';
import {compileSceneLayout, rectStyle} from '../layout/compile-layout';
import type {SceneTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';
import {sourceBarPresetRegistry} from '../templates/presentation-registry';
import {AdaptiveCaptionText} from '../shared/AdaptiveCaptionText';

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
  const template = props.template;
  if (!template) throw new Error('source_video requires a versioned template.');
  const tokens = template.design_tokens;
  const layout = compileSceneLayout(props, track.scene);
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
      data-scene-module="source_video"
      data-scene-variant={layout.variant.variant_id}
      style={{
        backgroundColor: tokens.background,
        color: tokens.foreground,
        fontFamily: tokens.body_font_family,
        overflow: 'hidden',
      }}
    >
      <div
        data-asset-boundary
        style={{
          position: 'absolute',
          ...rectStyle(layout.media),
          borderRadius: tokens.corner_radius,
          boxShadow: `0 18px ${tokens.shadow_blur}px rgba(0, 0, 0, 0.32)`,
          overflow: 'hidden',
        }}
      >
        <OffthreadVideo
          src={source}
          startFrom={startFrom}
          muted={track.asset.audio_mode === 'muted'}
          style={{width: '100%', height: '100%', objectFit: layout.mediaFit}}
        />
        <AbsoluteFill
          style={{
            background:
              'linear-gradient(180deg, rgba(0,0,0,0.34) 0%, transparent 24%, transparent 72%, rgba(0,0,0,0.58) 100%)',
            pointerEvents: 'none',
          }}
        />
      </div>
      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.source),
          alignItems: 'center',
          display: 'flex',
          justifyContent: 'space-between',
          color: tokens.accent,
          fontFamily: tokens.mono_font_family,
          fontSize: horizontal ? 17 : 21,
          gap: tokens.spacing_unit * 2,
          letterSpacing: 1.4,
          overflow: 'hidden',
        }}
      >
        <span>{sourceBarPresetRegistry.resolve(template.source_bar_preset).prefix}</span>
        <span style={{opacity: 0.7}}>·</span>
        <span style={{overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
          {track.asset.source_label}
        </span>
      </div>
      {caption ? (
        <div
          style={{
            position: 'absolute',
            ...rectStyle(layout.caption),
            alignItems: 'center',
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <AdaptiveCaptionText
            text={caption}
            baseFontSize={(horizontal ? 36 : 47) * tokens.caption_scale}
            charactersPerLine={horizontal ? 28 : 16}
            maxLines={tokens.caption_max_lines}
            color={tokens.foreground}
            fontFamily={tokens.caption_font_family}
            fontWeight={tokens.caption_weight}
            lineHeight={tokens.line_height}
            style={{
              backgroundColor: `${tokens.panel}e8`,
              border: `${tokens.border_width}px solid ${tokens.accent}55`,
              borderRadius: tokens.corner_radius,
              maxWidth: '100%',
              padding: horizontal ? '18px 34px' : '24px 34px',
            }}
          />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
