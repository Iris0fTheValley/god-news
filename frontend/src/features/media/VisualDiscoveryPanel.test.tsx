import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {CommonsVisualCandidate, Story} from '../../api/types';
import {scriptFixture, storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {VisualDiscoveryPanel} from './VisualDiscoveryPanel';

const apiMocks = vi.hoisted(() => ({
  approveVisualDiscoveryAsset: vi.fn(),
  listStoryVisualDiscoveryAssets: vi.fn(),
  rejectVisualDiscoveryAsset: vi.fn(),
  searchCommonsVisuals: vi.fn(),
  stageCommonsVisual: vi.fn(),
  visualDiscoveryAssetContentUrl: vi.fn((assetId: string) => `/media/${assetId}`),
}));

vi.mock('../../api/client', () => apiMocks);

const candidate: CommonsVisualCandidate = {
  file_title: 'File:Moon transit of sun large.ogv',
  page_id: 4250664,
  canonical_page_url: 'https://commons.wikimedia.org/wiki/File:Moon_transit_of_sun_large.ogv',
  direct_download_url: 'https://upload.wikimedia.org/moon.ogv',
  kind: 'video',
  mime_type: 'video/ogg',
  width: 1024,
  height: 768,
  duration_ms: 7933,
  size_bytes: 8078924,
  sha1: 'a21de698b16e94e58861336b33f324c26e3693da',
  attribution: {
    author: 'NASA',
    credit: 'NASA',
    attribution_text: 'NASA · Public domain',
  },
  rights: {
    license: 'public_domain',
    source_license_label: 'Public domain',
    license_url: null,
    allows_commercial_use: true,
    allows_derivatives: true,
    requires_attribution: false,
    requires_human_review: false,
  },
  video_derivatives: [],
};

const story = {
  ...storyFixture,
  status: 'DONE',
  script: {
    ...scriptFixture,
    revision: 3,
  },
} satisfies Story;

describe('VisualDiscoveryPanel', () => {
  beforeEach(() => {
    apiMocks.listStoryVisualDiscoveryAssets.mockResolvedValue([]);
    apiMocks.searchCommonsVisuals.mockResolvedValue({
      request: {query: 'NASA moon transit', limit: 10},
      candidates: [candidate],
    });
    apiMocks.stageCommonsVisual.mockResolvedValue({});
  });

  it('searches provider evidence and stages only the selected current segment', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualDiscoveryPanel story={story} />);

    await user.type(screen.getByPlaceholderText('例如：NASA moon transit'), 'NASA moon transit');
    await user.click(screen.getByRole('button', {name: '搜索素材'}));

    expect(await screen.findByText('Moon transit of sun large.ogv')).toBeVisible();
    expect(screen.getAllByText(/Public domain/)).toHaveLength(2);
    await user.click(screen.getByRole('button', {name: '下载并校验'}));

    await waitFor(() => expect(apiMocks.stageCommonsVisual).toHaveBeenCalledTimes(1));
    expect(apiMocks.stageCommonsVisual).toHaveBeenCalledWith(expect.objectContaining({
      file_title: candidate.file_title,
      story_id: story.story_id,
      segment_id: story.script?.segments[0]?.segment_id,
      expected_story_version: story.version,
      expected_script_revision: story.script?.revision,
    }));
  });
});
