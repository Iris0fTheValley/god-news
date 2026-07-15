import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {renderWithApp} from '../../test/render';
import {SourceManagementPage} from './SourceManagementPage';

const apiMocks = vi.hoisted(() => ({diagnoseSource: vi.fn(), getSourceHealth: vi.fn()}));

vi.mock('../../api/client', () => ({
  diagnoseSource: apiMocks.diagnoseSource,
  getSourceHealth: apiMocks.getSourceHealth,
}));

const report = {
  checked_at: '2026-07-12T08:00:00Z',
  network_probed: false,
  sources: [
    {
      source: 'dazhong',
      enabled: true,
      configured: true,
      authorized: false,
      reachable: null,
      contract_ok: true,
      access_method: 'authorized_public_page',
      notes: ['operator_acknowledgement_required'],
    },
    {
      source: 'reddit',
      enabled: true,
      configured: true,
      authorized: true,
      reachable: null,
      contract_ok: true,
      access_method: 'official_api',
      notes: [],
    },
    {
      source: 'guardian',
      enabled: true,
      configured: true,
      authorized: true,
      reachable: null,
      contract_ok: true,
      access_method: 'official_api',
      notes: [],
    },
    {
      source: 'pikabu',
      enabled: true,
      configured: false,
      authorized: false,
      reachable: null,
      contract_ok: true,
      access_method: 'authorized_public_page',
      notes: [],
    },
  ],
} as const;

describe('SourceManagementPage', () => {
  beforeEach(() => {
    apiMocks.getSourceHealth.mockResolvedValue(report);
    apiMocks.diagnoseSource.mockResolvedValue({
      source: 'reddit',
      outcome: 'verified',
      checked_at: '2026-07-15T06:00:00Z',
      credentials_verified: true,
      endpoint_reachable: true,
      attempts: [],
      errors: [],
    });
  });

  it('keeps authorization separate from network reachability and can request a probe', async () => {
    const user = userEvent.setup();
    renderWithApp(<SourceManagementPage />, ['/sources']);

    expect(await screen.findByText('大众新闻 · 开屏见好')).toBeVisible();
    expect(screen.getByText('等待授权')).toBeVisible();
    expect(screen.getByText('2/4 已授权')).toBeVisible();
    expect(screen.getAllByText('网络尚未探测')).toHaveLength(4);

    await user.click(screen.getByRole('button', {name: '核验网络'}));
    expect(apiMocks.getSourceHealth).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole('button', {name: '验证 Reddit OAuth'}));
    expect(apiMocks.diagnoseSource).toHaveBeenCalledWith('reddit');
    expect(await screen.findByText('凭据有效')).toBeVisible();
  });
});
