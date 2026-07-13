import {describe, expect, it} from 'vitest';

import {parseGodNewsVideoProps} from '../src/schema';
import {validProps} from './fixtures';

describe('GodNewsVideoPropsSchema', () => {
  it('accepts the backend ProductionManifest 1.0 shape', () => {
    expect(parseGodNewsVideoProps(validProps)).toEqual(validProps);
  });

  it('uses black as the forward-compatible transition fallback', () => {
    const legacy = structuredClone(validProps) as unknown as {
      manifest: {timeline: Array<{scene_transition?: string}>};
    };
    delete legacy.manifest.timeline[0]!.scene_transition;

    expect(parseGodNewsVideoProps(legacy).manifest.timeline[0]!.scene_transition).toBe('black');
  });

  it('rejects a non-contiguous timeline', () => {
    const invalid = structuredClone(validProps);
    invalid.manifest.timeline[1]!.start_ms = 1100;
    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /timeline must be contiguous/u,
    );
  });

  it('rejects runtime bindings for unknown segments', () => {
    const invalid = structuredClone(validProps);
    invalid.runtime_assets.audio_by_segment_id = {
      'e74261b9-a1bb-4cb7-a896-c8fa23099f71': 'assets/orphan.wav',
    };
    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /unknown segment_id/u,
    );
  });
});
