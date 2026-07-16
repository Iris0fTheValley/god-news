import type {
  EpisodeScene,
  GodNewsVideoProps,
  SourceVideoRenderAsset,
  TimelineSegment,
} from './schema';

export type IntroTrack = Readonly<{
  kind: 'intro';
  from: number;
  durationInFrames: number;
}>;

export type OutroTrack = Readonly<{
  kind: 'outro';
  from: number;
  durationInFrames: number;
}>;

export type SegmentTrack = Readonly<{
  kind: 'segment';
  from: number;
  durationInFrames: number;
  segment: TimelineSegment;
  scene: EpisodeScene;
}>;

export type SourceVideoTrack = Readonly<{
  kind: 'source_video';
  from: number;
  durationInFrames: number;
  scene: EpisodeScene;
  asset: SourceVideoRenderAsset;
}>;

export type TransitionTrack = Readonly<{
  kind: 'transition';
  from: number;
  durationInFrames: number;
  afterSceneId: string;
  transition_type: TimelineSegment['scene_transition'];
}>;

export type SceneTrack = SegmentTrack | SourceVideoTrack;
export type RenderTrack = IntroTrack | OutroTrack | SceneTrack | TransitionTrack;

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
  const outroFrames = millisecondsToFrames(props.outro_duration_ms, fps);
  const transitionFrames = millisecondsToFrames(
    props.transition_duration_ms,
    fps,
  );

  if (introFrames > 0) {
    tracks.push({kind: 'intro', from: cursor, durationInFrames: introFrames});
    cursor += introFrames;
  }

  const scenes = props.episode_plan?.scenes ?? props.manifest.timeline.map(
    (segment, index): EpisodeScene => ({
      scene_id: segment.segment_id,
      sequence: index,
      module_id: 'host_evidence',
      narration_segment_id: segment.segment_id,
      speaker_id: segment.speaker_id,
      host_visibility: 'visible',
      host_slot: 'primary',
      host_enter: index === 0,
      host_exit: index === props.manifest.timeline.length - 1,
      transition_type: segment.scene_transition,
    }),
  );

  const segmentsById = new Map(
    props.manifest.timeline.map((segment) => [segment.segment_id, segment]),
  );
  const sourceVideosById = new Map(
    props.source_videos.map((asset) => [asset.asset_id, asset]),
  );

  scenes.forEach((scene, index) => {
    if (scene.module_id === 'source_video') {
      const asset = scene.source_video_asset_id
        ? sourceVideosById.get(scene.source_video_asset_id)
        : undefined;
      if (!asset) {
        throw new Error(`Source video scene ${scene.scene_id} has no approved asset.`);
      }
      const durationInFrames = positiveMillisecondsToFrames(
        asset.out_ms - asset.in_ms,
        fps,
      );
      tracks.push({kind: 'source_video', from: cursor, durationInFrames, scene, asset});
      cursor += durationInFrames;
    } else {
      const segment = scene.narration_segment_id
        ? segmentsById.get(scene.narration_segment_id)
        : undefined;
      if (!segment) {
        throw new Error(`Narration scene ${scene.scene_id} has no reviewed segment.`);
      }
      const durationInFrames = positiveMillisecondsToFrames(
        segment.end_ms - segment.start_ms,
        fps,
      );
      tracks.push({kind: 'segment', from: cursor, durationInFrames, segment, scene});
      cursor += durationInFrames;
    }

    const isLast = index === scenes.length - 1;
    if ((!isLast || outroFrames > 0) && transitionFrames > 0) {
      tracks.push({
        kind: 'transition',
        from: cursor,
        durationInFrames: transitionFrames,
        afterSceneId: scene.scene_id,
        transition_type: scene.transition_type,
      });
      cursor += transitionFrames;
    }
  });

  if (outroFrames > 0) {
    tracks.push({kind: 'outro', from: cursor, durationInFrames: outroFrames});
    cursor += outroFrames;
  }

  return {fps, durationInFrames: cursor, tracks};
};
