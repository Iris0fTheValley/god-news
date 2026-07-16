import {Img, interpolate, useCurrentFrame} from 'remotion';

import {sourceForBrowser} from '../browser-assets';
import type {CompiledSceneLayout} from '../layout/compile-layout';
import type {GodNewsVideoProps, VisualRenderAsset} from '../schema';

export const resolveSceneVisuals = (
  props: GodNewsVideoProps,
  assetIds: readonly string[],
): VisualRenderAsset[] => {
  const assets = new Map(props.visual_assets.map((asset) => [asset.asset_id, asset]));
  return assetIds.map((assetId) => {
    const asset = assets.get(assetId);
    if (!asset) throw new Error(`Reviewed visual asset is missing: ${assetId}`);
    return asset;
  });
};

export const VisualAssetRenderer = ({
  props,
  asset,
  layout,
  variant,
}: {
  props: GodNewsVideoProps;
  asset: VisualRenderAsset;
  layout: CompiledSceneLayout;
  variant: 'framed' | 'full_bleed';
}) => {
  const frame = useCurrentFrame();
  const source = sourceForBrowser(
    props.runtime_assets.visual_by_asset_id[asset.asset_id] ?? asset.local_path,
  );
  if (!source) {
    throw new Error(`Reviewed visual asset was not staged: ${asset.asset_id}`);
  }
  const tokens = props.template?.design_tokens;
  if (!tokens) throw new Error('Visual asset rendering requires template design tokens.');
  const zoom = interpolate(
    frame,
    [0, 150],
    [tokens.image_zoom_min, tokens.image_zoom_max],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    },
  );
  return (
    <div
      data-asset-id={asset.asset_id}
      data-asset-type={asset.asset_type}
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        borderRadius: variant === 'framed' ? tokens.corner_radius : 0,
        border:
          variant === 'framed'
            ? `${tokens.border_width}px solid ${tokens.accent}88`
            : undefined,
        boxShadow:
          variant === 'framed'
            ? `0 24px ${tokens.shadow_blur}px ${tokens.background}88`
            : undefined,
        backgroundColor: tokens.panel,
      }}
    >
      <Img
        src={source}
        style={{
          width: '100%',
          height: '100%',
          objectFit: layout.mediaFit,
          transform: `scale(${zoom})`,
        }}
      />
    </div>
  );
};
