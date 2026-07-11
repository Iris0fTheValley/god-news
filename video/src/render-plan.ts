import type {GodNewsVideoProps, TimelineSegment} from './schema';

export type IntroTrack = Readonly<{
  kind: 'intro';
  from: number;
  durationInFrames: number;
}>;

export type SegmentTrack = Readonly<{
  kind: 'segment';
  from: number;
  durationInFrames: number;
  segment: TimelineSegment;
}>;

export type TransitionTrack = Readonly<{
  kind: 'transition';
  from: number;
  durationInFrames: number;
  afterSegmentId: string;
}>;

export type RenderTrack = IntroTrack | SegmentTrack | TransitionTrack;

export type RenderPlan = Readonly<{
  fps: number;
  durationInFrames: number;
  tracks: readonly RenderTrack[];
}>;

const millisecondsToFrames = (milliseconds: number, fps: number): number =>
  Math.round((milliseconds / 1000) * fps);

const positiveMillisecondsToFrames = (
  milliseconds: number,
  fps: number,
): number => Math.max(1, millisecondsToFrames(milliseconds, fps));

export const buildRenderPlan = (
  props: GodNewsVideoProps,
  fps: number,
): RenderPlan => {
  if (!Number.isInteger(fps) || fps <= 0) {
    throw new Error('fps must be a positive integer');
  }

  const tracks: RenderTrack[] = [];
  let cursor = 0;
  const introFrames = millisecondsToFrames(props.intro_duration_ms, fps);
  const transitionFrames = millisecondsToFrames(
    props.transition_duration_ms,
    fps,
  );

  if (introFrames > 0) {
    tracks.push({kind: 'intro', from: cursor, durationInFrames: introFrames});
    cursor += introFrames;
  }

  props.manifest.timeline.forEach((segment, index) => {
    const segmentFrames = positiveMillisecondsToFrames(
      segment.end_ms - segment.start_ms,
      fps,
    );
    tracks.push({
      kind: 'segment',
      from: cursor,
      durationInFrames: segmentFrames,
      segment,
    });
    cursor += segmentFrames;

    const isLast = index === props.manifest.timeline.length - 1;
    if (!isLast && transitionFrames > 0) {
      tracks.push({
        kind: 'transition',
        from: cursor,
        durationInFrames: transitionFrames,
        afterSegmentId: segment.segment_id,
      });
      cursor += transitionFrames;
    }
  });

  return {fps, durationInFrames: cursor, tracks};
};
