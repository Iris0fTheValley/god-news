import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

import {compileSceneLayout, rectStyle} from '../layout/compile-layout';
import {CaptionRenderer} from '../shared/CaptionRenderer';
import {SourceAttribution} from '../shared/SourceAttribution';
import {
  resolveSceneVisuals,
  VisualAssetRenderer,
} from '../shared/VisualAssetRenderer';
import type {EpisodeSceneRendererProps} from './types';

export const EvidenceFullscreenScene = ({
  props,
  track,
}: EpisodeSceneRendererProps) => {
  if (track.kind !== 'segment') {
    throw new Error('evidence_fullscreen requires a narration segment track');
  }
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const horizontal = width > height;
  const template = props.template;
  if (!template) throw new Error('evidence_fullscreen requires a versioned template.');
  const tokens = template.design_tokens;
  const layout = compileSceneLayout(props, track.scene);
  const assets = resolveSceneVisuals(props, track.scene.visual_asset_ids);
  const primary =
    assets.find(
      (asset) => asset.asset_id === track.scene.primary_visual_asset_id,
    ) ?? assets[0];
  if (!primary) {
    throw new Error('evidence_fullscreen requires reviewed visual evidence.');
  }
  const reveal = interpolate(frame, [0, 16], [0.985, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      data-scene-module="evidence_fullscreen"
      data-scene-variant={layout.variant.variant_id}
      style={{
        backgroundColor: tokens.background,
        color: tokens.foreground,
        fontFamily: tokens.body_font_family,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.media),
          transform: `scale(${reveal})`,
          transformOrigin: 'center',
        }}
      >
        <VisualAssetRenderer
          props={props}
          asset={primary}
          layout={layout}
          variant="framed"
        />
      </div>
      <div
        style={{
          position: 'absolute',
          ...rectStyle(layout.source),
          alignItems: 'center',
          display: 'flex',
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
          paddingInline: tokens.spacing_unit * 2,
        }}
      >
        <CaptionRenderer
          segment={track.segment}
          fontSize={Math.round(
            (horizontal ? 39 : 49) * tokens.caption_scale,
          )}
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
