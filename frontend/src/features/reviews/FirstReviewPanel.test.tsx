import {cleanup, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import type {RoleProfile} from '../../api/types';
import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {FirstReviewPanel} from './FirstReviewPanel';

const apiMocks = vi.hoisted(() => ({listRoles: vi.fn(), submitFirstReview: vi.fn()}));

vi.mock('../../api/client', () => ({
  listRoles: apiMocks.listRoles,
  submitFirstReview: apiMocks.submitFirstReview,
}));

const ttsRole: RoleProfile = {
  profile_id: 'c30b6fd9-9eae-43cb-b6c9-d05b4ce4d11a',
  slug: 'narrator',
  display_name: '默认旁白',
  kind: 'narrator',
  speaker_id: 'narrator',
  character_prompt: 'A clear news narrator.',
  default_emotion: 'happiness',
  default_spoken_language: 'en-US',
  default_speed: 1,
  default_pitch: 0,
  gpt_weights_path: 'voices/narrator.ckpt',
  sovits_weights_path: 'voices/narrator.pth',
  tts_model_profile: 'v2Pro',
  reference_language: 'all_zh',
  emotion_refs: {},
  tts_enabled: true,
  visual_assets: {},
  enabled: true,
  version: 1,
};

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe('FirstReviewPanel', () => {
  it('submits human-corrected key points with an idempotency id', async () => {
    const user = userEvent.setup();
    apiMocks.listRoles.mockResolvedValue([ttsRole]);
    apiMocks.submitFirstReview.mockResolvedValue(storyFixture);
    renderWithApp(<FirstReviewPanel story={storyFixture} />);

    const keyPoints = screen.getByLabelText('关键点（每行一条）');
    await user.clear(keyPoints);
    await user.type(keyPoints, '核对原始证据\n主人已确认接回');
    await waitFor(() => expect(screen.getByRole('button', {name: '批准并生成口播文本'})).toBeEnabled());
    await user.click(screen.getByRole('button', {name: '批准并生成口播文本'}));
    // ConfirmDialog opens — confirm the action
    const confirmButtons = screen.getAllByRole('button', {name: '批准并生成口播文本'});
    await user.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(apiMocks.submitFirstReview).toHaveBeenCalledOnce());
    const [storyId, payload] = apiMocks.submitFirstReview.mock.calls[0] as [string, Record<string, unknown>];
    expect(storyId).toBe(storyFixture.story_id);
    expect(payload).toMatchObject({
      decision: 'approve',
      expected_story_version: 3,
      corrected_key_points: ['核对原始证据', '主人已确认接回'],
    });
    expect(payload.preferences).toMatchObject({
      speaker_id: 'narrator',
      emotion: 'happiness',
      spoken_language: 'en-US',
      caption_language: 'zh-CN',
    });
    expect(payload.review_id).toEqual(expect.any(String));
  });

  it('does not permit approval until a loaded role is enabled and TTS-capable', async () => {
    apiMocks.listRoles.mockResolvedValue([{...ttsRole, tts_enabled: false}]);
    renderWithApp(<FirstReviewPanel story={storyFixture} />);

    await waitFor(() => expect(screen.getByText('仅显示可立即用于本地 TTS 的角色。')).toBeVisible());
    expect(screen.getByRole('button', {name: '批准并生成口播文本'})).toBeDisabled();
    expect(screen.getByText('批准前请选择一个已启用且具备完整本地 TTS 配置的角色。')).toBeVisible();
  });

  it('does not replace an unsupported legacy emotion with the story preference', async () => {
    apiMocks.listRoles.mockResolvedValue([{...ttsRole, default_emotion: 'neutral'}]);
    renderWithApp(<FirstReviewPanel story={storyFixture} />);

    await waitFor(() => expect(screen.getByText('仅显示可立即用于本地 TTS 的角色。')).toBeVisible());
    expect(screen.getByRole('button', {name: '批准并生成口播文本'})).toBeDisabled();
    expect(screen.getByRole('option', {name: '当前角色不可用于本地 TTS'})).toBeDisabled();
  });
});
