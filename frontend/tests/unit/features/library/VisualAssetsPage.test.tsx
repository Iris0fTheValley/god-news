import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {MediaCatalogEntry, MediaCatalogPage} from '@/api/types';
import {VisualAssetsPage} from '@/features/library/VisualAssetsPage';
import {renderWithApp} from '@test/render';

const apiMocks = vi.hoisted(() => ({
  archiveMediaCatalogAsset: vi.fn(),
  listMediaCatalogAssets: vi.fn(),
  restoreMediaCatalogAsset: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  ...apiMocks,
  mediaCatalogAssetContentUrl: (catalogId: string) => (
    `/api/media-assets/${encodeURIComponent(catalogId)}/content`
  ),
}));

const storyId = '11111111-1111-4111-8111-111111111111';
const assetId = '22222222-2222-4222-8222-222222222222';
const batchId = '33333333-3333-4333-8333-333333333333';

const asset = {
  catalog_id: `visual_discovery:${assetId}`,
  source_kind: 'visual_discovery',
  source_asset_id: assetId,
  media_kind: 'image',
  lifecycle: 'active',
  lifecycle_version: 1,
  story_id: storyId,
  segment_id: '44444444-4444-4444-8444-444444444444',
  script_revision: 2,
  filename: 'Community garden.jpg',
  mime_type: 'image/jpeg',
  sha256: 'a'.repeat(64),
  size_bytes: 65_536,
  width: 1600,
  height: 900,
  duration_ms: null,
  source_url: 'https://commons.wikimedia.org/wiki/File:Community_garden.jpg',
  external_preview_url: null,
  has_local_content: true,
  attribution: 'Open photographer · CC BY 4.0',
  license_label: 'CC BY 4.0',
  editorial_state: 'approved',
  publish_eligible: true,
  selectable: true,
  reusable: true,
  archived_at: null,
  archived_by: null,
  archive_reason: null,
  usages: [
    {
      purpose: 'story_segment',
      state: 'active',
      story_id: storyId,
      segment_id: '44444444-4444-4444-8444-444444444444',
      script_revision: 2,
      batch_id: null,
      scene_sequence: null,
      batch_version: null,
      render_input_sha256: null,
    },
    {
      purpose: 'batch_scene',
      state: 'frozen',
      story_id: storyId,
      segment_id: null,
      script_revision: null,
      batch_id: batchId,
      scene_sequence: 1,
      batch_version: 6,
      render_input_sha256: 'b'.repeat(64),
    },
  ],
} satisfies MediaCatalogEntry;

const page = {
  items: [asset],
  total: 1,
  limit: 200,
  offset: 0,
} satisfies MediaCatalogPage;

describe('VisualAssetsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listMediaCatalogAssets.mockResolvedValue(page);
    apiMocks.archiveMediaCatalogAsset.mockResolvedValue({
      ...asset,
      lifecycle: 'archived',
      lifecycle_version: 2,
      selectable: false,
    });
    apiMocks.restoreMediaCatalogAsset.mockResolvedValue(asset);
  });

  it('renders the global catalog with rights and real usage locations', async () => {
    const {container} = renderWithApp(<VisualAssetsPage />, ['/library/visual-assets']);

    expect(await screen.findByText('Community garden.jpg')).toBeVisible();
    expect(screen.getByText('Open photographer · CC BY 4.0')).toBeVisible();
    expect(screen.getByText('2 条使用记录')).toBeVisible();
    expect(
      container.querySelector(
        `img[src="/api/media-assets/${encodeURIComponent(asset.catalog_id)}/content"]`,
      ),
    ).not.toBeNull();

    await userEvent.setup().click(screen.getByText('2 条使用记录'));
    expect(screen.getByRole('link', {name: /批次 33333333/u})).toHaveAttribute(
      'href',
      `/production/batches?batch=${batchId}`,
    );
    expect(screen.getByRole('link', {name: /故事 11111111/u})).toHaveAttribute(
      'href',
      `/stories/${storyId}`,
    );
  });

  it('archives through the versioned lifecycle contract', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualAssetsPage />, ['/library/visual-assets']);

    await user.click(await screen.findByRole('button', {name: '归档'}));
    const dialog = screen.getByRole('dialog', {name: '归档素材'});
    await user.type(within(dialog).getByRole('textbox', {name: '操作原因'}), '素材已过期');
    await user.click(within(dialog).getByRole('button', {name: '确认变更'}));

    await waitFor(() => {
      expect(apiMocks.archiveMediaCatalogAsset).toHaveBeenCalledWith(
        asset.catalog_id,
        {
          expected_version: 1,
          operator_id: 'frontend-operator',
          reason: '素材已过期',
        },
      );
    });
  });
});
