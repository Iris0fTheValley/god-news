import {describe, expect, it} from 'vitest';

import {canEditNarration, canPreviewBatchNarration} from './narrationReviewState';

describe('canEditNarration', () => {
  it('allows revisions after narration approval and before batch TTS', () => {
    expect(canEditNarration('PENDING_BATCH_TTS')).toBe(true);
  });

  it('does not expose an editor while batch TTS is running', () => {
    expect(canEditNarration('PROCESSING_BATCH_TTS')).toBe(false);
  });

  it('only exposes the batch audio preview at the pending timeline review gate', () => {
    expect(canPreviewBatchNarration('PENDING_TIMELINE_REVIEW', true)).toBe(true);
    expect(canPreviewBatchNarration('PENDING_TIMELINE_REVIEW', false)).toBe(false);
    expect(canPreviewBatchNarration('PENDING_BATCH_TTS', true)).toBe(false);
  });
});
