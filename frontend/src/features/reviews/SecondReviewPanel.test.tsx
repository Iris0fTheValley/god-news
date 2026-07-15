import {cleanup, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import type {Story} from '../../api/types';
import {scriptFixture, storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {SecondReviewPanel} from './SecondReviewPanel';

const apiMocks = vi.hoisted(() => ({submitSecondReview: vi.fn()}));

vi.mock('../../api/client', () => ({submitSecondReview: apiMocks.submitSecondReview}));

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

function finalReviewStory(): Story {
  return {...storyFixture, status: 'PENDING_SECOND_REVIEW', script: scriptFixture};
}

describe('SecondReviewPanel', () => {
  it('records an unchanged-script concern without clearing audio', async () => {
    const user = userEvent.setup();
    const story = finalReviewStory();
    apiMocks.submitSecondReview.mockResolvedValue(story);
    renderWithApp(<SecondReviewPanel story={story} revisedScript={scriptFixture} />);

    await user.type(screen.getByLabelText('审核说明'), '请复核第二段的停顿。');
    await user.click(screen.getByRole('button', {name: '记录问题，保留音频'}));
    await user.click(screen.getByRole('button', {name: '记录问题'}));

    await waitFor(() => expect(apiMocks.submitSecondReview).toHaveBeenCalledOnce());
    expect(apiMocks.submitSecondReview).toHaveBeenCalledWith(story.story_id, expect.objectContaining({
      decision: 'request_changes',
      revised_script: null,
    }));
  });

  it('does not clear audio when only the server-managed script revision differs', async () => {
    const user = userEvent.setup();
    const story = finalReviewStory();
    apiMocks.submitSecondReview.mockResolvedValue(story);
    renderWithApp(
      <SecondReviewPanel story={story} revisedScript={{...scriptFixture, revision: 99}} />,
    );

    await user.type(screen.getByLabelText('审核说明'), '重新确认音频与脚本一致。');
    await user.click(screen.getByRole('button', {name: '记录问题，保留音频'}));
    await user.click(screen.getByRole('button', {name: '记录问题'}));

    await waitFor(() => expect(apiMocks.submitSecondReview).toHaveBeenCalledOnce());
    expect(apiMocks.submitSecondReview).toHaveBeenCalledWith(story.story_id, expect.objectContaining({
      decision: 'request_changes',
      revised_script: null,
    }));
  });

  it('returns an actually revised script to the script-review gate', async () => {
    const user = userEvent.setup();
    const story = finalReviewStory();
    const revisedText = '修订后的第一段。';
    const revisedScript = {
      ...scriptFixture,
      segments: [
        {
          ...scriptFixture.segments[0],
          spoken_text: revisedText,
          captions: scriptFixture.segments[0].captions?.map((caption) => (
            caption.kind === 'verbatim' ? {...caption, text: revisedText} : caption
          )),
        },
        ...scriptFixture.segments.slice(1),
      ],
    };
    apiMocks.submitSecondReview.mockResolvedValue(story);
    renderWithApp(<SecondReviewPanel story={story} revisedScript={revisedScript} />);

    await user.click(screen.getByRole('button', {name: '保存脚本并返回审核'}));
    await user.click(screen.getByRole('button', {name: '保存并返回审核'}));

    await waitFor(() => expect(apiMocks.submitSecondReview).toHaveBeenCalledOnce());
    expect(apiMocks.submitSecondReview).toHaveBeenCalledWith(story.story_id, expect.objectContaining({
      decision: 'request_changes',
      revised_script: revisedScript,
    }));
  });
});
