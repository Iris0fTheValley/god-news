import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {renderWithApp} from '../../test/render';
import {storyFixture} from '../../test/fixtures';
import {StoryListPage} from './StoryListPage';

const apiMocks = vi.hoisted(() => ({
  listStories: vi.fn(),
  createStory: vi.fn(),
  deleteStory: vi.fn(),
  getClassificationMetrics: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  listStories: apiMocks.listStories,
  createStory: apiMocks.createStory,
  deleteStory: apiMocks.deleteStory,
  getClassificationMetrics: apiMocks.getClassificationMetrics,
}));

describe('StoryListPage', () => {
  beforeEach(() => {
    apiMocks.listStories.mockResolvedValue([storyFixture]);
    apiMocks.getClassificationMetrics.mockResolvedValue({
      reviewed_count: 4,
      accepted_count: 3,
      accuracy: 0.75,
    });
  });

  it('shows the production state and opens an accessible ingest dialog', async () => {
    const user = userEvent.setup();
    renderWithApp(<StoryListPage />);

    expect(await screen.findByText('陌生人把走失的小狗送回了家')).toBeVisible();
    expect(screen.getByText('等待初审', {selector: '.status-chip'})).toBeVisible();
    expect(screen.getByText('1 条')).toBeVisible();
    expect(screen.getByText(/75% \/ 4 次复核/u)).toBeVisible();

    await user.click(screen.getByRole('button', {name: '新建故事'}));
    expect(screen.getByRole('dialog', {name: '加入一条候选内容'})).toBeVisible();
  });
});
