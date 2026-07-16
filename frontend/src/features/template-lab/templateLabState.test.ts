import {describe, expect, it} from 'vitest';

import {
  DEFAULT_TEMPLATE_LAB_STATE,
  readTemplateLabState,
  writeTemplateLabState,
} from './templateLabState';

describe('templateLabState', () => {
  it('round-trips every reproducible selector through URL search params', () => {
    const expected = {
      ...DEFAULT_TEMPLATE_LAB_STATE,
      scene: 'host_evidence' as const,
      variant: 'host_corner_full_bleed',
      profile: 'douyin_vertical' as const,
      fixture: 'host-corner-volunteers',
      frame: 73,
      zoom: 0.35,
      assetBounds: true,
      hostBounds: true,
      captionBounds: true,
      hostVisible: true,
      hostSlot: 'corner' as const,
      hostVideoUrl: 'https://example.test/host.webm',
      tokenPreset: 'high_contrast' as const,
      title: '可复现标题',
      caption: '可复现字幕',
    };

    expect(readTemplateLabState(writeTemplateLabState(expected))).toEqual(expected);
  });

  it('rejects unknown enum values and clamps numeric controls', () => {
    const state = readTemplateLabState(
      new URLSearchParams('scene=invented&profile=square&frame=-5&zoom=9'),
    );

    expect(state.scene).toBe(DEFAULT_TEMPLATE_LAB_STATE.scene);
    expect(state.profile).toBe(DEFAULT_TEMPLATE_LAB_STATE.profile);
    expect(state.frame).toBe(0);
    expect(state.zoom).toBe(0.8);
  });
});
