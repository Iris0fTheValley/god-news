import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';

import type {Story} from '../../api/types';
import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {TtsSynthesisPanel} from './TtsSynthesisPanel';

const apiMocks = vi.hoisted(() => ({synthesizeStory: vi.fn()}));

vi.mock('../../api/client', () => ({synthesizeStory: apiMocks.synthesizeStory}));

describe('TtsSynthesisPanel', () => {
  it('starts local TTS only after explicit confirmation', async () => {
    const user = userEvent.setup();
    const story: Story = {...storyFixture, status: 'PENDING_TTS'};
    apiMocks.synthesizeStory.mockResolvedValue(story);
    renderWithApp(<TtsSynthesisPanel story={story} />);

    await user.click(screen.getByRole('button', {name: '启动本地 TTS'}));
    expect(apiMocks.synthesizeStory).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', {name: '启动合成'}));

    await waitFor(() => expect(apiMocks.synthesizeStory).toHaveBeenCalledWith(story.story_id, {
      expected_story_version: story.version,
    }));
  });
});
