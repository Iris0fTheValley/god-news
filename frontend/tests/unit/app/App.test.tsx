import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {useLocation} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {App} from '@/app/App';
import {renderWithApp} from '@test/render';

const apiMocks = vi.hoisted(() => ({
  getReadiness: vi.fn(),
  getRuntimeControlStatus: vi.fn(),
  requestRuntimeAction: vi.fn(),
}));

vi.mock('@/api/client', () => apiMocks);
vi.mock('@/features/stories/StoryListPage', () => ({
  StoryListPage: () => (
    <div>
      stories-page
      <input data-global-search aria-label="故事全局搜索" />
    </div>
  ),
}));
vi.mock('@/features/stories/StoryWorkbenchPage', () => ({
  StoryWorkbenchPage: () => <div>story-workbench-page</div>,
}));
vi.mock('@/features/sources/SourceManagementPage', () => ({
  SourceManagementPage: () => <div>source-management-page</div>,
}));
vi.mock('@/features/sources/SourceRunsPage', () => ({
  SourceRunsPage: () => <div>source-runs-page</div>,
}));
vi.mock('@/features/video/VideoBatchesPage', () => ({
  VideoBatchesPage: () => <div>video-batches-page</div>,
}));
vi.mock('@/features/library/VisualAssetsPage', () => ({
  VisualAssetsPage: () => <div>visual-assets-page</div>,
}));
vi.mock('@/features/roles/RolesPage', () => ({
  RolesPage: () => <div>roles-page</div>,
}));
vi.mock('@/features/bgm/BgmPage', () => ({
  BgmPage: () => <div>bgm-page</div>,
}));
vi.mock('@/features/visual-modules/VisualModulesPage', () => ({
  VisualModulesPage: () => <div>visual-modules-page</div>,
}));
vi.mock('@/features/template-lab/TemplateLabPage', () => ({
  TemplateLabPage: () => {
    const location = useLocation();
    return <div>scene-lab-page{location.search}</div>;
  },
}));
vi.mock('@/features/ops/OpsPage', () => ({
  OpsPage: () => <div>ops-page</div>,
}));

describe('App shell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getReadiness.mockResolvedValue({ready: true, checks: []});
    apiMocks.getRuntimeControlStatus.mockResolvedValue({
      enabled: true,
      supervised: true,
      process_id: 1234,
      pending_action: null,
    });
    Object.defineProperty(window, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('renders two primary sections with contextual side navigation', async () => {
    renderWithApp(<App />, ['/template-lab?fixture=host-volunteers&host=1']);

    expect(
      await screen.findByText('scene-lab-page?fixture=host-volunteers&host=1'),
    ).toBeVisible();
    const navigation = screen.getByLabelText('一级导航');
    expect(within(navigation).getAllByRole('link')).toHaveLength(2);
    expect(within(navigation).getByRole('link', {name: /主功能/u})).toBeVisible();
    expect(
      within(navigation).getByRole('link', {name: /素材库/u}),
    ).toHaveAttribute('aria-current', 'page');
    const sidebar = screen.getByLabelText('素材库侧边导航');
    expect(within(sidebar).getByRole('heading', {name: '素材与角色'})).toBeVisible();
    expect(within(sidebar).getByRole('heading', {name: '视觉系统'})).toBeVisible();
    expect(
      within(sidebar).getByRole('link', {name: /Scene Lab/u}),
    ).toHaveAttribute('aria-current', 'page');
  });

  it('opens shortcut help, focuses global search, and follows numeric navigation', async () => {
    renderWithApp(<App />, ['/stories']);
    await screen.findByText('stories-page');

    fireEvent.keyDown(window, {key: '?'});
    expect(screen.getByRole('dialog', {name: '快捷键参考'})).toBeVisible();
    fireEvent.keyDown(window, {key: 'Escape'});
    expect(screen.queryByRole('dialog', {name: '快捷键参考'})).not.toBeInTheDocument();

    const search = screen.getByRole('textbox', {name: '故事全局搜索'});
    fireEvent.keyDown(window, {key: '/'});
    expect(search).toHaveFocus();

    search.blur();
    fireEvent.keyDown(window, {key: '7'});
    expect(await screen.findByText('visual-modules-page')).toBeVisible();
  });

  it('keeps backend restart behind an explicit header confirmation', async () => {
    const user = userEvent.setup();
    apiMocks.requestRuntimeAction.mockResolvedValue({
      command_id: '22222222-2222-4222-8222-222222222222',
      action: 'restart',
      accepted_at: new Date().toISOString(),
      process_id: 1234,
    });
    renderWithApp(<App />, ['/stories']);
    await screen.findByText('stories-page');

    const restart = screen.getByRole('button', {name: '重启后端'});
    await waitFor(() => expect(restart).toBeEnabled());
    await user.click(restart);
    const dialog = screen.getByRole('dialog', {name: '重启后端'});
    expect(apiMocks.requestRuntimeAction).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', {name: '确认重启'}));

    expect(apiMocks.requestRuntimeAction.mock.calls[0]?.[0]).toBe('restart');
  });
});
