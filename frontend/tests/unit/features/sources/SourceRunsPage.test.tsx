import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {SourceRunsPage} from '@/features/sources/SourceRunsPage';
import {renderWithApp} from '@test/render';

const apiMocks = vi.hoisted(() => ({
  cancelSourceRun: vi.fn(),
  getSourceRun: vi.fn(),
  getSourceSchedule: vi.fn(),
  listSourceRuns: vi.fn(),
  startSourceRun: vi.fn(),
  startSourceSchedule: vi.fn(),
  stopSourceSchedule: vi.fn(),
}));

vi.mock('@/api/client', () => apiMocks);

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

  it('reports policy-filtered items separately from ingestion failures', async () => {
    apiMocks.listSourceRuns.mockResolvedValue([
      {
        run_id: '7e4c7dde-7832-4a18-a8ef-f7adfdd7f15e',
        request: {source: 'guardian'},
        status: 'completed',
        ingested_count: 0,
        failed_count: 0,
        filtered_count: 1,
        duplicate_count: 0,
        created_at: '2026-08-03T01:00:00Z',
        started_at: '2026-08-03T01:00:00Z',
        finished_at: '2026-08-03T01:00:01Z',
        version: 2,
      },
    ]);

    renderWithApp(<SourceRunsPage />, ['/source-runs']);

    expect(await screen.findByText(/成功 0.*失败 0.*过滤 1/)).toBeVisible();
  });
});
