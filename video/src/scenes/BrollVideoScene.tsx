import {AbsoluteFill, OffthreadVideo, useVideoConfig} from 'remotion';

import {sourceForBrowser} from '../browser-assets';
import {compileSceneLayout, rectStyle} from '../layout/compile-layout';
import type {SceneTrack} from '../render-plan';
import type {GodNewsVideoProps} from '../schema';

export const BrollVideoScene = ({
  props,
  track,
}: {
  props: GodNewsVideoProps;
  track: SceneTrack;
  segmentCount: number;
}) => {
  if (track.kind !== 'broll_video') {
    throw new Error('broll_video requires an approved B-roll track');
  }
  const {fps, width, height} = useVideoConfig();
  const horizontal = width > height;
  const template = props.template;
  if (!template) throw new Error('broll_video requires a versioned template.');
  const tokens = template.design_tokens;
  const layout = compileSceneLayout(props, track.scene);
  const source = sourceForBrowser(track.asset.local_path);
  if (!source) {
    throw new Error('Approved B-roll was not staged for browser rendering.');
  }
  const startFrom = Math.round((track.asset.in_ms / 1000) * fps);

  return (
    <AbsoluteFill
      data-scene-module="broll_video"
      data-scene-variant={layout.variant.variant_id}
      data-broll-source-url={track.asset.source_url}
      data-broll-license={track.asset.license}
      data-broll-attribution={track.asset.attribution}
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
          muted
          style={{width: '100%', height: '100%', objectFit: layout.mediaFit}}
        />
        <AbsoluteFill
          style={{
            background:
              'linear-gradient(180deg, rgba(0,0,0,0.16) 0%, transparent 62%, rgba(0,0,0,0.5) 100%)',
            pointerEvents: 'none',
          }}
        />
      </div>
      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.source),
          alignItems: horizontal ? 'center' : 'flex-start',
          display: 'flex',
          flexDirection: horizontal ? 'row' : 'column',
          justifyContent: horizontal ? 'space-between' : 'center',
          color: tokens.accent,
          fontFamily: tokens.mono_font_family,
          fontSize: horizontal ? 16 : 19,
          gap: horizontal ? tokens.spacing_unit * 2 : 1,
          letterSpacing: 0.7,
          overflow: 'hidden',
        }}
      >
        <span style={{overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
          B-ROLL · {track.asset.source_label}
        </span>
        <span style={{overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
          {track.asset.license} · {track.asset.attribution}
        </span>
      </div>
    </AbsoluteFill>
  );
};
