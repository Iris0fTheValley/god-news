import type {GodNewsVideoProps} from './schema';

export const sampleProps: GodNewsVideoProps = {
  manifest: {
    schema_version: '1.0',
    story_id: '2bc6e989-33d7-45ad-87cd-7a57bbba85f4',
    script_revision: 1,
    language: 'zh-CN',
    total_duration_ms: 7600,
    timeline: [
      {
        segment_id: 'de443fa0-6f3a-4ced-a480-82b4f936467c',
        sequence: 0,
        start_ms: 0,
        end_ms: 3400,
        text: '一个普通的善意举动，也能让陌生人的一天重新亮起来。',
        speaker_id: 'narrator',
        emotion: 'warm',
        scene_transition: 'mood_shift',
        visual_hint: '一束晨光穿过城市街道',
        audio_path: 'studio-placeholder/segment-0.wav',
      },
      {
        segment_id: '1e5544e5-08b0-4381-8557-7097df912f20',
        sequence: 1,
        start_ms: 3400,
        end_ms: 7600,
        text: '新闻不只记录世界，也提醒我们，温柔一直存在。',
        speaker_id: 'narrator',
        emotion: 'hopeful',
        scene_transition: 'black',
        visual_hint: '人物剪影和柔和的绿色光带',
        audio_path: 'studio-placeholder/segment-1.wav',
      },
    ],
  },
  title: '今天，善意被看见',
  subtitle: 'GOD NEWS · HUMAN KINDNESS',
  intro_duration_ms: 700,
  transition_duration_ms: 180,
  theme: {
    background: '#101512',
    foreground: '#f3f1e8',
    accent: '#85a77d',
    signal: '#e4a853',
  },
  visual_reservations: {
    renderer: 'placeholder',
  },
  output_profiles: [
    {
      profile_id: 'douyin_vertical',
      width: 1080,
      height: 1920,
      fps: 30,
      layout: 'vertical',
    },
    {
      profile_id: 'bilibili_horizontal',
      width: 1920,
      height: 1080,
      fps: 30,
      layout: 'horizontal',
    },
  ],
  runtime_assets: {
    audio_by_segment_id: {},
    output_profile_id: 'douyin_vertical',
  },
};
