import {describe, expect, it} from 'vitest';

import {buildRenderPlan} from '../src/render-plan';
import {registeredEpisodeSceneModules} from '../src/scenes/SceneRegistry';
import {validProps} from './fixtures';

describe('buildRenderPlan', () => {
  it('adds deterministic intro and transition frames around audio segments', () => {
    const plan = buildRenderPlan(validProps, 30);

    expect(plan.durationInFrames).toBe(96);
    expect(plan.tracks.map((track) => ({
      kind: track.kind,
      from: track.from,
      durationInFrames: track.durationInFrames,
      ...(track.kind === 'transition' ? {transition_type: track.transition_type} : {}),
    }))).toEqual([
      {kind: 'intro', from: 0, durationInFrames: 15},
      {kind: 'segment', from: 15, durationInFrames: 30},
      {
        kind: 'transition',
        from: 45,
        durationInFrames: 6,
        transition_type: 'crossfade',
      },
      {kind: 'segment', from: 51, durationInFrames: 45},
    ]);
  });

  it('never drops a positive-duration segment below one frame', () => {
    const props = structuredClone(validProps);
    props.manifest.total_duration_ms = 2;
    props.manifest.timeline = [
      {
        ...props.manifest.timeline[0]!,
        start_ms: 0,
        end_ms: 2,
      },
    ];
    props.episode_plan = undefined;
    props.intro_duration_ms = 0;
    props.transition_duration_ms = 0;

    expect(buildRenderPlan(props, 30).durationInFrames).toBe(1);
  });

  it('rejects invalid frame rates', () => {
    expect(() => buildRenderPlan(validProps, 0)).toThrow(/positive integer/u);
    expect(() => buildRenderPlan(validProps, 29.97)).toThrow(/positive integer/u);
  });

  it('binds each reviewed segment to its registered semantic scene', () => {
    const segmentTracks = buildRenderPlan(validProps, 30).tracks.filter(
      (track) => track.kind === 'segment',
    );

    expect(segmentTracks.map((track) => track.scene.module_id)).toEqual([
      'host_evidence',
      'evidence_fullscreen',
    ]);
    expect(registeredEpisodeSceneModules).toEqual([
      'host_evidence',
      'evidence_fullscreen',
      'source_video',
    ]);
  });

  it('derives original source-video duration from the approved selected range', () => {
    const props = structuredClone(validProps);
    const assetId = 'e67be87a-d750-44c7-a463-fd6e27789b42';
    props.source_videos = [
      {
        asset_id: assetId,
        story_id: props.manifest.story_id,
        transcription_id: 'a16eafda-a9d7-4db4-a5c7-e2354dbfb9a9',
        transcription_version: 2,
        transcription_review: {
          reviewer_id: 'caption-editor',
          decision: 'approve',
          reviewed_version: 1,
          note: null,
          reviewed_at: '2026-07-15T00:00:00Z',
        },
        local_path: 'video/source.mp4',
        sha256: 'a'.repeat(64),
        size_bytes: 2048,
        duration_ms: 8000,
        width: 1920,
        height: 1080,
        in_ms: 1000,
        out_ms: 3500,
        audio_mode: 'original',
        source_label: 'Example source',
        captions: [
          {
            cue_id: '12655f69-38cd-49fa-b479-dd87175135fb',
            sequence: 0,
            start_ms: 1000,
            end_ms: 3500,
            captions: [{language: 'zh-CN', kind: 'verbatim', text: '已审核字幕'}],
          },
        ],
      },
    ];
    props.episode_plan!.scenes.push({
      scene_id: '8219be88-d3bf-41cf-bee7-ee733b49d06f',
      sequence: 2,
      module_id: 'source_video',
      narration_segment_id: null,
      source_video_asset_id: assetId,
      speaker_id: null,
      host_visibility: 'hidden',
      host_slot: null,
      host_enter: false,
      host_exit: false,
      transition_type: 'black',
    });

    const plan = buildRenderPlan(props, 30);
    const sourceTrack = plan.tracks.find((track) => track.kind === 'source_video');
    expect(sourceTrack?.durationInFrames).toBe(75);
    expect(sourceTrack?.asset.asset_id).toBe(assetId);
    expect(plan.durationInFrames).toBe(177);
  });
});
