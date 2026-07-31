import {fireEvent, screen, within} from '@testing-library/react';
import {useLocation} from 'react-router-dom';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import {App} from '@/app/App';
import {renderWithApp} from '@test/render';

const apiMocks = vi.hoisted(() => ({
  getReadiness: vi.fn(),
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
    Object.defineProperty(window, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('renders grouped navigation and redirects legacy routes to their new owner', async () => {
    renderWithApp(<App />, ['/template-lab?fixture=host-volunteers&host=1']);

    expect(
      await screen.findByText('scene-lab-page?fixture=host-volunteers&host=1'),
    ).toBeVisible();
    const navigation = screen.getByLabelText('主导航');
    for (const heading of ['编辑流程', '采集', '节目制作', '资源库', '视觉系统', '系统']) {
      expect(within(navigation).getByRole('heading', {name: heading})).toBeVisible();
    }
    expect(
      within(navigation).getByRole('link', {name: /Scene Lab/u}),
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
});
