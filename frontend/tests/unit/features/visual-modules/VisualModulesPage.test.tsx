import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {VideoTemplateDefinition} from '@/api/types';
import {VisualModulesPage} from '@/features/visual-modules/VisualModulesPage';
import {renderWithApp} from '@test/render';
import {worldWarmthTemplate} from '@god-news/video/player';

const apiMocks = vi.hoisted(() => ({
  listVideoTemplates: vi.fn(),
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

describe('VisualModulesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listVideoTemplates.mockResolvedValue([
      structuredClone(worldWarmthTemplate) as VideoTemplateDefinition,
    ]);
  });

  it('reads the backend registry and reports parity with the renderer contract', async () => {
    renderWithApp(<VisualModulesPage />, ['/visual/modules']);

    await waitFor(() => expect(apiMocks.listVideoTemplates).toHaveBeenCalledOnce());
    expect(await screen.findByText('后端与渲染器一致')).toBeVisible();
    for (const moduleId of worldWarmthTemplate.capabilities.supported_modules) {
      expect(screen.getAllByText(moduleId).length).toBeGreaterThan(0);
    }
    expect(
      screen.getByText(
        new RegExp(
          `${worldWarmthTemplate.capabilities.supported_profiles.length}\\s*种`,
          'u',
        ),
      ),
    ).toBeVisible();
  });

  it('previews a registered module through the production Player fixture', async () => {
    const user = userEvent.setup();
    renderWithApp(<VisualModulesPage />, ['/visual/modules']);

    expect(await screen.findByTestId('production-module-player')).toBeVisible();
    expect(playerMock.mock.lastCall?.[0]).toMatchObject({
      compositionWidth: 1920,
      compositionHeight: 1080,
      inputProps: {
        template: {template_id: worldWarmthTemplate.template_id},
      },
    });

    await user.selectOptions(
      screen.getByRole('combobox', {name: '输出比例'}),
      'douyin_vertical',
    );
    await waitFor(() => {
      expect(playerMock.mock.lastCall?.[0]).toMatchObject({
        compositionWidth: 1080,
        compositionHeight: 1920,
      });
    });
  });
});
