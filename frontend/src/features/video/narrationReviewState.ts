import type {VideoBatchStatus} from '../../api/types';

export function canEditNarration(status: VideoBatchStatus): boolean {
  return [
    'PENDING_NARRATION_REVIEW',
    'PENDING_BATCH_TTS',
    'PENDING_TIMELINE_REVIEW',
  ].includes(status);
}

export function canPreviewBatchNarration(
  status: VideoBatchStatus,
  hasAudio: boolean,
): boolean {
  return status === 'PENDING_TIMELINE_REVIEW' && hasAudio;
}
