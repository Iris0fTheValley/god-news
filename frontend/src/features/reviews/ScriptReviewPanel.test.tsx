import {cleanup, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';

import type {Story} from '../../api/types';
import {scriptFixture, storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {ScriptReviewPanel} from './ScriptReviewPanel';

const apiMocks = vi.hoisted(() => ({submitScriptReview: vi.fn()}));

vi.mock('../../api/client', () => ({submitScriptReview: apiMocks.submitScriptReview}));

afterEach(cleanup);

describe('ScriptReviewPanel', () => {
  it('persists a revised script without starting TTS', async () => {
    const user = userEvent.setup();
    const story: Story = {...storyFixture, status: 'SCRIPT_READY', script: scriptFixture};
    apiMocks.submitScriptReview.mockResolvedValue(story);
    renderWithApp(<ScriptReviewPanel story={story} revisedScript={scriptFixture} hasUnsavedChanges />);

    await user.click(screen.getByRole('button', {name: '保存修订，继续审稿'}));
    await user.click(screen.getByRole('button', {name: '保存修订'}));

    await waitFor(() => expect(apiMocks.submitScriptReview).toHaveBeenCalledOnce());
    const [storyId, payload] = apiMocks.submitScriptReview.mock.calls[0] as [string, Record<string, unknown>];
    expect(storyId).toBe(story.story_id);
    expect(payload).toMatchObject({
      decision: 'request_changes',
      expected_story_version: story.version,
      revised_script: scriptFixture,
    });
  });

  it('requires saving edits before approval', () => {
    const story: Story = {...storyFixture, status: 'SCRIPT_READY', script: scriptFixture};
    renderWithApp(<ScriptReviewPanel story={story} revisedScript={scriptFixture} hasUnsavedChanges />);
    expect(screen.getByRole('button', {name: '批准脚本'})).toBeDisabled();
  });
});
