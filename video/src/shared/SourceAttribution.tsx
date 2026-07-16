import type {VisualRenderAsset} from '../schema';
import {sourceBarPresetRegistry} from '../templates/presentation-registry';

export const SourceAttribution = ({
  asset,
  color,
  fontFamily,
  presetId,
}: {
  asset: VisualRenderAsset;
  color: string;
  fontFamily: string;
  presetId: string;
}) => (
  <div
    data-source-attribution
    style={{
      alignItems: 'center',
      color,
      display: 'flex',
      fontFamily,
      fontSize: 17,
      gap: 12,
      letterSpacing: 1.2,
      overflow: 'hidden',
      whiteSpace: 'nowrap',
    }}
  >
    <span>{sourceBarPresetRegistry.resolve(presetId).prefix}</span>
    <span style={{opacity: 0.7}}>·</span>
    <span style={{overflow: 'hidden', textOverflow: 'ellipsis'}}>
      {asset.source_label}
    </span>
  </div>
);
