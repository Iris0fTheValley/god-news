import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

import {compileSceneLayout, rectStyle} from '../layout/compile-layout';
import {CaptionRenderer} from '../shared/CaptionRenderer';
import {HostRenderer} from '../shared/HostRenderer';
import {SourceAttribution} from '../shared/SourceAttribution';
import {
  resolveSceneVisuals,
  VisualAssetRenderer,
} from '../shared/VisualAssetRenderer';
import type {EpisodeSceneRendererProps} from './types';

const HostEvidenceBase = ({
  props,
  track,
  fullBleed,
}: EpisodeSceneRendererProps & {fullBleed: boolean}) => {
  if (track.kind !== 'segment') {
    throw new Error('host_evidence requires a narration segment track');
  }
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const horizontal = width > height;
  const template = props.template;
  if (!template) throw new Error('host_evidence requires a versioned template.');
  const tokens = template.design_tokens;
  const layout = compileSceneLayout(props, track.scene);
  const assets = resolveSceneVisuals(props, track.scene.visual_asset_ids);
  const primary =
    assets.find(
      (asset) => asset.asset_id === track.scene.primary_visual_asset_id,
    ) ?? assets[0];
  if (!primary) {
    throw new Error('host_evidence requires reviewed visual evidence.');
  }
  const titleOpacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const captionFont = Math.round(
    (horizontal ? 39 : 49) * tokens.caption_scale,
  );

  return (
    <AbsoluteFill
      data-scene-module="host_evidence"
      data-scene-variant={layout.variant.variant_id}
      style={{
        background: `radial-gradient(circle at 84% 12%, ${tokens.accent}2e, transparent 35%), ${tokens.background}`,
        color: tokens.foreground,
        fontFamily: tokens.body_font_family,
        overflow: 'hidden',
      }}
    >
      <div style={{position: 'absolute', ...rectStyle(layout.media)}}>
        <VisualAssetRenderer
          props={props}
          asset={primary}
          layout={layout}
          variant={fullBleed ? 'full_bleed' : 'framed'}
        />
        {fullBleed ? (
          <AbsoluteFill
            style={{
              background:
                'linear-gradient(90deg, rgba(9,13,10,0.1), rgba(9,13,10,0.02) 55%, rgba(9,13,10,0.5))',
            }}
          />
        ) : null}
      </div>

      {layout.host ? (
        <div
          data-host-slot={track.scene.host_slot}
          style={{
            position: 'absolute',
            ...rectStyle(layout.host),
            zIndex: 3,
            filter: `drop-shadow(0 18px ${tokens.shadow_blur}px ${tokens.background})`,
          }}
        >
          <HostRenderer props={props} track={track} />
        </div>
      ) : null}

      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.source),
          alignItems: 'center',
          display: 'flex',
          opacity: titleOpacity,
          paddingInline: tokens.spacing_unit * 2,
        }}
      >
        <SourceAttribution
          asset={primary}
          color={tokens.accent}
          fontFamily={tokens.mono_font_family}
          presetId={template.source_bar_preset}
        />
      </div>

      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.caption),
          alignItems: 'center',
          display: 'flex',
          justifyContent: 'center',
          padding: `${tokens.spacing_unit}px ${tokens.spacing_unit * 2}px`,
        }}
      >
        <CaptionRenderer
          segment={track.segment}
          fontSize={captionFont}
          maxLines={tokens.caption_max_lines}
          color={tokens.foreground}
          fontFamily={tokens.caption_font_family}
          fontWeight={tokens.caption_weight}
          lineHeight={tokens.line_height}
          presetId={template.caption_preset}
          charactersPerLine={horizontal ? 28 : 16}
        />
      </div>
    </AbsoluteFill>
  );
};

export const HostEvidenceSplitScene = (props: EpisodeSceneRendererProps) => (
  <HostEvidenceBase {...props} fullBleed={false} />
);

export const HostEvidenceFullBleedScene = (
  props: EpisodeSceneRendererProps,
) => <HostEvidenceBase {...props} fullBleed />;
