import {describe, expect, it} from 'vitest';

import {resolveVisualObjectFit} from '../src/shared/VisualAssetRenderer';

describe('resolveVisualObjectFit', () => {
  it('preserves a portrait whose face would be cropped by a landscape panel', () => {
    expect(
      resolveVisualObjectFit(
        {asset_type: 'image'},
      ),
    ).toBe('contain');
  });

  it('always preserves the full reviewed source screenshot', () => {
    expect(
      resolveVisualObjectFit(
        {asset_type: 'source_screenshot'},
      ),
    ).toBe('contain');
  });
});
