import {describe, expect, it} from 'vitest';

import {buildRenderPlan} from '../src/render-plan';
import {validProps} from './fixtures';

describe('buildRenderPlan', () => {
  it('adds deterministic intro and transition frames around audio segments', () => {
    const plan = buildRenderPlan(validProps, 30);

    expect(plan.durationInFrames).toBe(96);
    expect(plan.tracks.map(({kind, from, durationInFrames}) => ({
      kind,
      from,
      durationInFrames,
    }))).toEqual([
      {kind: 'intro', from: 0, durationInFrames: 15},
      {kind: 'segment', from: 15, durationInFrames: 30},
      {kind: 'transition', from: 45, durationInFrames: 6},
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
    props.intro_duration_ms = 0;
    props.transition_duration_ms = 0;

    expect(buildRenderPlan(props, 30).durationInFrames).toBe(1);
  });

  it('rejects invalid frame rates', () => {
    expect(() => buildRenderPlan(validProps, 0)).toThrow(/positive integer/u);
    expect(() => buildRenderPlan(validProps, 29.97)).toThrow(/positive integer/u);
  });
});
