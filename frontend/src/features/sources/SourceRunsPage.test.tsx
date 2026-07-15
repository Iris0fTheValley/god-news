import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {renderWithApp} from '../../test/render';
import {SourceRunsPage} from './SourceRunsPage';

const apiMocks = vi.hoisted(() => ({
  cancelSourceRun: vi.fn(),
  getSourceRun: vi.fn(),
  getSourceSchedule: vi.fn(),
  listSourceRuns: vi.fn(),
  startSourceRun: vi.fn(),
  startSourceSchedule: vi.fn(),
  stopSourceSchedule: vi.fn(),
}));

vi.mock('../../api/client', () => apiMocks);

const disabledSchedule = {
  schedule_id: 'source-auto-collection',
  enabled: false,
  next_run_at: null,
  last_tick_at: null,
  last_started_run_ids: {},
  ready_sources: ['guardian'],
  active_runs: [],
  version: 1,
  updated_at: '2026-07-15T06:00:00Z',
} as const;

describe('SourceRunsPage automatic collection controls', () => {
  beforeEach(() => {
    apiMocks.listSourceRuns.mockResolvedValue([]);
    apiMocks.getSourceSchedule.mockResolvedValue(disabledSchedule);
    apiMocks.startSourceSchedule.mockResolvedValue({
      ...disabledSchedule,
      enabled: true,
      next_run_at: '2026-07-15T06:30:00Z',
      version: 2,
    });
  });

  it('starts automation without exposing a cadence input', async () => {
    const user = userEvent.setup();
    renderWithApp(<SourceRunsPage />, ['/source-runs']);

    expect(await screen.findByText('自动采集：已停止')).toBeVisible();
    expect(screen.queryByLabelText(/频率|间隔/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: '启动自动采集'}));
    expect(apiMocks.startSourceSchedule).toHaveBeenCalledOnce();
    expect(await screen.findByText('自动采集：运行中')).toBeVisible();
  });
});
