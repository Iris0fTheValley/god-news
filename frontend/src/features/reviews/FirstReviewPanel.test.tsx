import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';

import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {FirstReviewPanel} from './FirstReviewPanel';

const apiMocks = vi.hoisted(() => ({submitFirstReview: vi.fn()}));

vi.mock('../../api/client', () => ({
  submitFirstReview: apiMocks.submitFirstReview,
}));

describe('FirstReviewPanel', () => {
  it('submits human-corrected key points with an idempotency id', async () => {
    const user = userEvent.setup();
    apiMocks.submitFirstReview.mockResolvedValue(storyFixture);
    renderWithApp(<FirstReviewPanel story={storyFixture} />);

    const keyPoints = screen.getByLabelText('关键点（每行一条）');
    await user.clear(keyPoints);
    await user.type(keyPoints, '核对原始证据\n主人已确认接回');
    await user.click(screen.getByRole('button', {name: '批准并生成音频'}));
    // ConfirmDialog opens — confirm the action
    const confirmButtons = screen.getAllByRole('button', {name: '批准并生成音频'});
    await user.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(apiMocks.submitFirstReview).toHaveBeenCalledOnce());
    const [storyId, payload] = apiMocks.submitFirstReview.mock.calls[0] as [string, Record<string, unknown>];
    expect(storyId).toBe(storyFixture.story_id);
    expect(payload).toMatchObject({
      decision: 'approve',
      expected_story_version: 3,
      corrected_key_points: ['核对原始证据', '主人已确认接回'],
    });
    expect(payload.review_id).toEqual(expect.any(String));
  });
});
