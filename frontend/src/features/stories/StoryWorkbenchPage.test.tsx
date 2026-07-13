import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {Route, Routes} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {Story} from '../../api/types';
import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {StoryWorkbenchPage} from './StoryWorkbenchPage';

const apiMocks = vi.hoisted(() => ({
  deleteStory: vi.fn(),
  getProductionManifest: vi.fn(),
  getStory: vi.fn(),
  listReviews: vi.fn(),
  listTransitions: vi.fn(),
  reopenStory: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  deleteStory: apiMocks.deleteStory,
  getProductionManifest: apiMocks.getProductionManifest,
  getStory: apiMocks.getStory,
  listReviews: apiMocks.listReviews,
  listTransitions: apiMocks.listTransitions,
  reopenStory: apiMocks.reopenStory,
}));

const doneStory: Story = {...storyFixture, status: 'DONE'};

describe('StoryWorkbenchPage', () => {
  beforeEach(() => {
    apiMocks.getStory.mockResolvedValue(doneStory);
    apiMocks.listReviews.mockResolvedValue([]);
    apiMocks.listTransitions.mockResolvedValue([]);
    apiMocks.getProductionManifest.mockResolvedValue({
      story_id: doneStory.story_id,
      story_version: doneStory.version,
      total_duration_ms: 0,
      timeline: [],
    });
    apiMocks.deleteStory.mockResolvedValue({...doneStory, status: 'ARCHIVED'});
  });

  it('returns to the active queue after a successful archive', async () => {
    const user = userEvent.setup();
    renderWithApp(
      <Routes>
        <Route path="/stories" element={<p>已导航到队列</p>} />
        <Route path="/stories/:storyId" element={<StoryWorkbenchPage />} />
      </Routes>,
      [`/stories/${doneStory.story_id}`],
    );

    await screen.findByRole('heading', {name: doneStory.source.title});
    await user.click(screen.getByRole('button', {name: '归档故事'}));
    await user.click(screen.getByRole('button', {name: '确认归档'}));

    await waitFor(() => expect(apiMocks.deleteStory).toHaveBeenCalled());
    expect(apiMocks.deleteStory.mock.calls[0]?.[0]).toBe(doneStory.story_id);
    expect(await screen.findByText('已导航到队列')).toBeVisible();
  });
});
