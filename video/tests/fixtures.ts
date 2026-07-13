import type {GodNewsVideoProps} from '../src/schema';

export const validProps: GodNewsVideoProps = {
  manifest: {
    schema_version: '1.0',
    story_id: 'b942617e-7b92-44f6-9601-62291fc60bcc',
    script_revision: 2,
    language: 'zh-CN',
    total_duration_ms: 2500,
    timeline: [
      {
        segment_id: '46f90b41-ecb7-4397-b446-854349573eb9',
        sequence: 0,
        start_ms: 0,
        end_ms: 1000,
        text: '第一段',
        speaker_id: 'narrator',
        emotion: 'neutral',
        scene_transition: 'crossfade',
        visual_hint: null,
        audio_path: 'audio/first.wav',
      },
      {
        segment_id: '2f538aba-26bd-46af-a94c-4e31075a2104',
        sequence: 1,
        start_ms: 1000,
        end_ms: 2500,
        text: '第二段',
        speaker_id: 'guest',
        emotion: 'warm',
        scene_transition: 'black',
        visual_hint: 'soft light',
        audio_path: 'audio/second.wav',
      },
    ],
  },
  title: 'Deterministic fixture',
  subtitle: null,
  intro_duration_ms: 500,
  transition_duration_ms: 200,
  theme: {
    background: '#101512',
    foreground: '#f3f1e8',
    accent: '#85a77d',
    signal: '#e4a853',
  },
  visual_reservations: {renderer: 'placeholder'},
  runtime_assets: {audio_by_segment_id: {}},
};
