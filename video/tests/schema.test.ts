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

  it('accepts immutable Live2D host media for every reviewed segment', () => {
    const input = structuredClone(validProps);
    input.visual_reservations = {
      renderer: 'live2d_prerender',
      host_videos: input.manifest.timeline.map((segment, index) => ({
        asset_id: index === 0
          ? '4aebecf9-4092-4816-84d1-1ce05c1600dc'
          : '247b4a03-533f-44f7-bbd4-3fd3f462e169',
        segment_id: segment.segment_id,
        speaker_id: segment.speaker_id,
        role_profile_id: index === 0
          ? '6b5eeefc-c4c2-4263-8764-6a8596938308'
          : 'ec0a064d-265e-40d6-8cbb-300e02561c58',
        role_profile_version: 2,
        model_sha256: 'a'.repeat(64),
        audio_sha256: 'b'.repeat(64),
        local_path: `hosts/${segment.segment_id}.webm`,
        sha256: 'c'.repeat(64),
        size_bytes: 2048,
        duration_ms: segment.end_ms - segment.start_ms,
        width: 720,
        height: 720,
        fps: 30,
        video_codec: 'vp9',
      })),
    };

    expect(parseGodNewsVideoProps(input).visual_reservations.renderer).toBe(
      'live2d_prerender',
    );
  });

  it('rejects Live2D host media that drifts from reviewed speaker identity', () => {
    const input = structuredClone(validProps);
    input.visual_reservations = {
      renderer: 'live2d_prerender',
      host_videos: input.manifest.timeline.map((segment, index) => ({
        asset_id: index === 0
          ? '4aebecf9-4092-4816-84d1-1ce05c1600dc'
          : '247b4a03-533f-44f7-bbd4-3fd3f462e169',
        segment_id: segment.segment_id,
        speaker_id: index === 0 ? 'different-speaker' : segment.speaker_id,
        role_profile_id: index === 0
          ? '6b5eeefc-c4c2-4263-8764-6a8596938308'
          : 'ec0a064d-265e-40d6-8cbb-300e02561c58',
        role_profile_version: 2,
        model_sha256: 'a'.repeat(64),
        audio_sha256: 'b'.repeat(64),
        local_path: `hosts/${segment.segment_id}.webm`,
        sha256: 'c'.repeat(64),
        size_bytes: 2048,
        duration_ms: segment.end_ms - segment.start_ms,
        width: 720,
        height: 720,
        fps: 30,
        video_codec: 'vp9',
      })),
    };

    expect(() => parseGodNewsVideoProps(input)).toThrow(
      /host identity and duration must match narration/u,
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
      visual_asset_ids: [],
    });

    expect(() => parseGodNewsVideoProps(invalid)).toThrow(
      /source video scenes must match approved assets/u,
    );
  });
});
