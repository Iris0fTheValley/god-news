import type {StoryStatus} from '../api/types';

export const STORY_STATUSES = [
  'FETCHED',
  'TRANSLATED',
  'PENDING_FIRST_REVIEW',
  'PROCESSING_SCRIPT',
  'SCRIPT_READY',
  'PENDING_SECOND_REVIEW',
  'DONE',
] as const satisfies readonly StoryStatus[];

export const STATUS_LABELS: Record<StoryStatus, string> = {
  FETCHED: '已抓取',
  TRANSLATED: '已翻译',
  PENDING_FIRST_REVIEW: '等待初审',
  PROCESSING_SCRIPT: '生成脚本',
  SCRIPT_READY: '脚本就绪',
  PENDING_SECOND_REVIEW: '等待终审',
  DONE: '已完成',
};
