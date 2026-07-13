import type {SceneTransition, SpeechEmotion} from '../api/types';

export const SPEECH_EMOTIONS = [
  'happiness',
  'sadness',
  'anger',
  'disgust',
  'like',
  'surprise',
  'fear',
] as const satisfies readonly SpeechEmotion[];

export const SPEECH_EMOTION_LABELS: Record<SpeechEmotion, string> = {
  happiness: '喜悦',
  sadness: '悲伤',
  anger: '愤怒',
  disgust: '厌恶',
  like: '喜爱',
  surprise: '惊讶',
  fear: '恐惧',
};

export const SCENE_TRANSITIONS = [
  'black',
  'crossfade',
  'slide',
  'wipe',
  'mood_shift',
] as const satisfies readonly SceneTransition[];

export const SCENE_TRANSITION_LABELS: Record<SceneTransition, string> = {
  black: '黑场',
  crossfade: '叠化',
  slide: '滑动',
  wipe: '划像',
  mood_shift: '情绪转场',
};
