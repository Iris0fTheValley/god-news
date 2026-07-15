import {describe, expect, it} from 'vitest';

import {parseGodNewsVideoProps} from '../src/schema';
import {validProps} from './fixtures';

describe('GodNewsVideoPropsSchema', () => {
  it('accepts the backend structured ProductionManifest 2.0 shape', () => {
    expect(parseGodNewsVideoProps(validProps)).toEqual(validProps);
  });

  it('rejects captions that drift from the exact spoken text', () => {
    const invalid = structuredClone(validProps);
    invalid.manifest.timeline[0]!.captions[0]!.text = 'different';
    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /verbatim caption must match spoken text and language/u,
    );
  });

  it('uses black as the forward-compatible transition fallback', () => {
    const legacy = structuredClone(validProps) as unknown as {
      manifest: {timeline: Array<{scene_transition?: string}>};
      episode_plan: {scenes: Array<{transition_type?: string}>};
    };
    delete legacy.manifest.timeline[0]!.scene_transition;
    delete legacy.episode_plan.scenes[0]!.transition_type;

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

  it('requires the active output profile to come from the semantic snapshot', () => {
    const invalid = structuredClone(validProps);
    invalid.output_profiles = invalid.output_profiles.filter(
      (profile) => profile.profile_id !== 'bilibili_horizontal',
    );
    invalid.runtime_assets.output_profile_id = 'bilibili_horizontal';
    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /runtime output profile is not declared/u,
    );
  });

  it('accepts one plan for both platform-specific dimensions', () => {
    const vertical = parseGodNewsVideoProps(validProps);
    const horizontal = parseGodNewsVideoProps({
      ...validProps,
      runtime_assets: {
        ...validProps.runtime_assets,
        output_profile_id: 'bilibili_horizontal',
      },
    });
    expect(vertical.manifest).toEqual(horizontal.manifest);
    expect(vertical.runtime_assets.output_profile_id).toBe('douyin_vertical');
    expect(horizontal.runtime_assets.output_profile_id).toBe('bilibili_horizontal');
  });

  it('rejects unregistered scene modules before rendering', () => {
    const invalid = structuredClone(validProps) as unknown as {
      episode_plan: {scenes: Array<{module_id: string}>};
    };
    invalid.episode_plan.scenes[0]!.module_id = 'invented_by_a_model';

    expect(() => parseGodNewsVideoProps(invalid)).toThrow();
  });

  it('rejects scene capabilities that contradict host visibility', () => {
    const invalid = structuredClone(validProps);
    invalid.episode_plan!.scenes[0]!.host_visibility = 'hidden';
    invalid.episode_plan!.scenes[0]!.host_slot = null;

    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /host_evidence requires a visible host/u,
    );
  });

  it('rejects scene identity that drifts from reviewed narration', () => {
    const invalid = structuredClone(validProps);
    invalid.episode_plan!.scenes[0]!.speaker_id = 'unreviewed-speaker';

    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /scene identity must match reviewed narration/u,
    );
  });

  it('rejects a source-video scene without an approved registered asset', () => {
    const invalid = structuredClone(validProps);
    invalid.episode_plan!.scenes.push({
      scene_id: 'fcbb4b68-8807-46c6-8967-2f18e7ceeeeb',
      sequence: 2,
      module_id: 'source_video',
      narration_segment_id: null,
      source_video_asset_id: 'fdb03c41-2c67-4494-b560-7c9d68db39e0',
      speaker_id: null,
      host_visibility: 'hidden',
      host_slot: null,
      host_enter: false,
      host_exit: false,
      transition_type: 'black',
    });

    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /source video scenes must match approved assets/u,
    );
  });
});
