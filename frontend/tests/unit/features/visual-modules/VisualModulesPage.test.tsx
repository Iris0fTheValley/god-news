import {screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {
  VideoCapabilityView,
  VideoRegistryView,
  VideoTemplateDefinition,
} from '@/api/types';
import {VisualModulesPage} from '@/features/visual-modules/VisualModulesPage';
import {renderWithApp} from '@test/render';
import {
  type EpisodeSceneModule,
  worldWarmthTemplate,
} from '@god-news/video/player';

const apiMocks = vi.hoisted(() => ({
  getVideoCapabilityRegistry: vi.fn(),
  listVideoTemplates: vi.fn(),
  setVideoCapabilityPolicy: vi.fn(),
}));
interface PlayerFixtureProps {
  compositionWidth: number;
  compositionHeight: number;
  inputProps: {template?: {template_id: string}};
}

const playerMock = vi.hoisted(() => vi.fn<(props: PlayerFixtureProps) => void>());

vi.mock('@/api/client', () => apiMocks);
vi.mock('@remotion/player', () => ({
  Player: (props: PlayerFixtureProps) => {
    playerMock(props);
    return <div data-testid="production-module-player">production Player fixture</div>;
  },
}));

const moduleCapability = (moduleId: EpisodeSceneModule): VideoCapabilityView => ({
  key: `module:${moduleId}`,
  kind: 'module',
  display_name: moduleId,
  registered: true,
  configurable: true,
  policy: {
    key: `module:${moduleId}`,
    enabled_for_new_batches: true,
    version: 1,
    reason: null,
    updated_by: null,
    updated_at: null,
  },
  effective_enabled: true,
  disabled_by: [],
  dependencies: [],
  used_by: [`template:${worldWarmthTemplate.template_id}@${worldWarmthTemplate.template_version}`],
  supported_profiles: [...worldWarmthTemplate.capabilities.supported_profiles],
  supported_host_slots: [],
  active_batch_ids: moduleId === 'evidence_fullscreen'
    ? ['11111111-1111-4111-8111-111111111111']
    : [],
  usage_count: moduleId === 'evidence_fullscreen' ? 1 : 0,
});

const registry = {
  capabilities: worldWarmthTemplate.capabilities.supported_modules.map(moduleCapability),
} satisfies VideoRegistryView;

describe('VisualModulesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listVideoTemplates.mockResolvedValue([
      structuredClone(worldWarmthTemplate) as VideoTemplateDefinition,
    ]);
    apiMocks.getVideoCapabilityRegistry.mockResolvedValue(registry);
    apiMocks.setVideoCapabilityPolicy.mockResolvedValue(registry);
  });

  it('reads contract definitions and operational usage from the backend registry', async () => {
    renderWithApp(<VisualModulesPage />, ['/visual/modules']);

    await waitFor(() => {
      expect(apiMocks.listVideoTemplates).toHaveBeenCalledOnce();
      expect(apiMocks.getVideoCapabilityRegistry).toHaveBeenCalledOnce();
    });
    expect(await screen.findByText('后端与渲染器一致')).toBeVisible();
    expect(screen.getByText('1 个视频批次')).toBeVisible();
    expect(screen.getByRole('link', {name: '批次 11111111'})).toHaveAttribute(
      'href',
      '/production/batches?batch=11111111-1111-4111-8111-111111111111',
    );
  });

  it('changes the new-batch policy with optimistic version evidence', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualModulesPage />, ['/visual/modules']);

    expect(await screen.findByTestId('production-module-player')).toBeVisible();
    await user.click(screen.getByRole('button', {name: '停用模块'}));
    const dialog = screen.getByRole('dialog', {name: '停用视觉模块'});
    await user.type(
      within(dialog).getByRole('textbox', {name: '操作原因'}),
      '临时维护渲染组件',
    );
    await user.click(within(dialog).getByRole('button', {name: '确认策略变更'}));

    await waitFor(() => {
      expect(apiMocks.setVideoCapabilityPolicy).toHaveBeenCalledWith({
        key: 'module:evidence_fullscreen',
        enabled_for_new_batches: false,
        expected_version: 1,
        reason: '临时维护渲染组件',
        operator_id: 'frontend-operator',
      });
    });
  });
});
