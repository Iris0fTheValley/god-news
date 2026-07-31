import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {
  CommonsVisualCandidate,
  Story,
  StoryVisualAssets,
  VisualDiscoveryAssetView,
} from '@/api/types';
import {VisualAssetsPage} from '@/features/library/VisualAssetsPage';
import {scriptFixture, storyFixture} from '@test/fixtures';
import {renderWithApp} from '@test/render';

const apiMocks = vi.hoisted(() => ({
  approveVisualDiscoveryAsset: vi.fn(),
  listSourceMediaArtifacts: vi.fn(),
  listStories: vi.fn(),
  listStoryVisualAssets: vi.fn(),
  listStoryVisualDiscoveryAssets: vi.fn(),
  rejectVisualDiscoveryAsset: vi.fn(),
  reuseApprovedVisualDiscoveryAsset: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  ...apiMocks,
  sourceMediaContentUrl: (storyId: string, artifactId: string) => (
    `/api/source-media/${storyId}/${artifactId}`
  ),
  visualAssetContentUrl: (storyId: string, assetId: string) => (
    `/api/visual-assets/${storyId}/${assetId}`
  ),
  visualDiscoveryAssetContentUrl: (assetId: string) => (
    `/api/visual-discovery/${assetId}`
  ),
}));

const sourceStoryId = '11111111-1111-4111-8111-111111111111';
const targetStoryId = '22222222-2222-4222-8222-222222222222';
const sourceSegmentId = '33333333-3333-4333-8333-333333333333';
const targetSegmentId = '44444444-4444-4444-8444-444444444444';

const sourceStory = {
  ...storyFixture,
  story_id: sourceStoryId,
  status: 'SCRIPT_READY',
  title: '脚本就绪故事',
  script: {
    ...scriptFixture,
    segments: [
      {...scriptFixture.segments[0], segment_id: sourceSegmentId},
    ],
  },
} satisfies Story;

const targetStory = {
  ...storyFixture,
  story_id: targetStoryId,
  status: 'DONE',
  title: '可复用目标故事',
  script: {
    ...scriptFixture,
    revision: 4,
    segments: [
      {...scriptFixture.segments[0], segment_id: targetSegmentId},
    ],
  },
} satisfies Story;

const noScriptStory = {
  ...storyFixture,
  story_id: '55555555-5555-4555-8555-555555555555',
  title: '尚未生成脚本',
  script: null,
} satisfies Story;

const storyAssets = {
  story_id: sourceStoryId,
  story_version: sourceStory.version,
  script_revision: sourceStory.script.revision,
  source_page_url: 'https://news.example.test/good-story',
  source_page_screenshot: {
    asset_id: '66666666-6666-4666-8666-666666666666',
    content_type: 'image/png',
    filename: 'source-page.png',
    origin: 'source_page_screenshot',
    script_revision: sourceStory.script.revision,
    segment_id: null,
    sha256: 'a'.repeat(64),
    size_bytes: 32_768,
    story_id: sourceStoryId,
  },
  segment_assets: [],
} satisfies StoryVisualAssets;

const commonsCandidate = (fileTitle: string): CommonsVisualCandidate => ({
  file_title: fileTitle,
  page_id: fileTitle === 'File:Staged.jpg' ? 101 : 102,
  canonical_page_url: `https://commons.wikimedia.org/wiki/${fileTitle}`,
  direct_download_url: `https://upload.wikimedia.org/${fileTitle}`,
  kind: 'image',
  mime_type: 'image/jpeg',
  width: 1600,
  height: 900,
  duration_ms: null,
  size_bytes: 4096,
  sha1: 'b'.repeat(40),
  attribution: {
    author: 'Open photographer',
    credit: 'Open photographer',
    attribution_text: 'Open photographer · CC BY 4.0',
  },
  rights: {
    license: 'cc_by',
    source_license_label: 'CC BY 4.0',
    license_url: 'https://creativecommons.org/licenses/by/4.0/',
    allows_commercial_use: true,
    allows_derivatives: true,
    requires_attribution: true,
    requires_human_review: false,
  },
  video_derivatives: [],
});

const discoveryAsset = (
  assetId: string,
  status: VisualDiscoveryAssetView['status'],
  title: string,
): VisualDiscoveryAssetView => ({
  asset_id: assetId,
  candidate: commonsCandidate(title),
  created_at: '2026-07-31T12:00:00Z',
  downloaded_size_bytes: 4096,
  probed_duration_ms: null,
  review_note: null,
  reviewed_at: status === 'approved' ? '2026-07-31T12:05:00Z' : null,
  script_revision: sourceStory.script.revision,
  segment_id: sourceSegmentId,
  sha256: 'c'.repeat(64),
  status,
  story_id: sourceStoryId,
});

const stagedAsset = discoveryAsset(
  '77777777-7777-4777-8777-777777777777',
  'staged',
  'File:Staged.jpg',
);
const approvedAsset = discoveryAsset(
  '88888888-8888-4888-8888-888888888888',
  'approved',
  'File:Approved.jpg',
);
const rejectedAsset = discoveryAsset(
  '99999999-9999-4999-8999-999999999999',
  'rejected',
  'File:Rejected.jpg',
);

describe('VisualAssetsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listStories.mockResolvedValue([
      noScriptStory,
      sourceStory,
      targetStory,
    ]);
    apiMocks.listStoryVisualAssets.mockResolvedValue(storyAssets);
    apiMocks.listStoryVisualDiscoveryAssets.mockResolvedValue([
      stagedAsset,
      approvedAsset,
      rejectedAsset,
    ]);
    apiMocks.listSourceMediaArtifacts.mockResolvedValue([]);
    apiMocks.approveVisualDiscoveryAsset.mockResolvedValue({
      ...stagedAsset,
      status: 'approved',
    });
    apiMocks.rejectVisualDiscoveryAsset.mockResolvedValue({
      ...stagedAsset,
      status: 'rejected',
    });
    apiMocks.reuseApprovedVisualDiscoveryAsset.mockResolvedValue({});
  });

  it('lists only stories with scripts and renders persisted visual assets', async () => {
    const {container} = renderWithApp(<VisualAssetsPage />, ['/library/visual-assets']);

    const storySelect = await screen.findByRole('combobox', {name: '故事'});
    await within(storySelect).findByRole('option', {name: sourceStory.title});
    const optionLabels = within(storySelect)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(optionLabels).toEqual(['脚本就绪故事', '可复用目标故事']);
    expect(optionLabels).not.toContain('尚未生成脚本');

    expect(await screen.findByText('source-page.png')).toBeVisible();
    expect(screen.getByText('来源网页截图')).toBeVisible();
    expect(
      container.querySelector(
        `img[src="/api/visual-assets/${sourceStoryId}/${storyAssets.source_page_screenshot.asset_id}"]`,
      ),
    ).not.toBeNull();
  });

  it('reviews staged Commons assets and opens reuse controls for approved assets', async () => {
    const user = userEvent.setup();
    const {container} = renderWithApp(
      <VisualAssetsPage />,
      ['/library/visual-assets'],
    );

    expect(await screen.findByText('File:Staged.jpg')).toBeVisible();
    expect(
      container.querySelector(
        `img[src="${stagedAsset.candidate.direct_download_url}"]`,
      ),
    ).not.toBeNull();
    expect(
      container.querySelector(
        `img[src="/api/visual-discovery/${approvedAsset.asset_id}"]`,
      ),
    ).not.toBeNull();
    expect(screen.getAllByText('已拒绝').length).toBeGreaterThan(0);
    expect(screen.getByText('1 个待权利审核')).toBeVisible();
    await user.click(screen.getByRole('button', {name: '批准素材'}));
    await waitFor(() => {
      expect(apiMocks.approveVisualDiscoveryAsset).toHaveBeenCalledWith(
        stagedAsset.asset_id,
        expect.objectContaining({expected_story_version: sourceStory.version}),
      );
    });

    await user.click(screen.getByRole('button', {name: '拒绝'}));
    await waitFor(() => {
      expect(apiMocks.rejectVisualDiscoveryAsset).toHaveBeenCalledWith(
        stagedAsset.asset_id,
        expect.objectContaining({expected_story_version: sourceStory.version}),
      );
    });

    await user.click(screen.getByRole('button', {name: '复用到其他故事'}));
    const dialog = screen.getByRole('dialog', {name: '复用已批准素材'});
    expect(within(dialog).getByRole('combobox', {name: '目标故事'})).toHaveValue(
      targetStoryId,
    );
    expect(within(dialog).getByRole('combobox', {name: '目标脚本段'})).toHaveValue(
      targetSegmentId,
    );
    expect(
      within(dialog).getByRole('button', {name: '创建待审复用记录'}),
    ).toBeEnabled();
  });
});
