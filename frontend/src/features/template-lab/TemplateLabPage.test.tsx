import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';

import {renderWithApp} from '../../test/render';
import {TemplateLabPage} from './TemplateLabPage';

vi.mock('@remotion/player', async () => {
  const React = await import('react');
  return {
    Player: React.forwardRef(function MockPlayer() {
      return <div data-testid="production-remotion-player">production player</div>;
    }),
  };
});

describe('TemplateLabPage', () => {
  it('renders the production player for an available evidence fixture', () => {
    renderWithApp(<TemplateLabPage />, [
      '/template-lab?template=world_warmth&version=1.0.0&scene=evidence_fullscreen&variant=evidence_documentary&profile=bilibili_horizontal&fixture=evidence-source-page&frame=0',
    ]);

    expect(screen.getByRole('heading', {name: '模板实验室'})).toBeInTheDocument();
    expect(screen.getByTestId('production-remotion-player')).toBeInTheDocument();
    expect(screen.getByText('1920×1080')).toBeInTheDocument();
    expect(
      screen.getByRole('button', {name: '复制当前帧截图命令'}),
    ).toBeEnabled();
    expect(
      screen.getByRole('button', {name: '复制视觉回归命令'}),
    ).toBeEnabled();
  });

  it('stops instead of drawing a fake host when Live2D media is missing', async () => {
    const user = userEvent.setup();
    renderWithApp(<TemplateLabPage />, ['/template-lab']);

    await user.selectOptions(screen.getByRole('combobox', {name: 'Fixture'}), 'host-volunteers');

    expect(screen.queryByTestId('production-remotion-player')).not.toBeInTheDocument();
    expect(screen.getByText('该状态不可预览')).toBeInTheDocument();
    expect(
      screen.getAllByText(/缺少真实 Live2D 预渲染 URL/u).length,
    ).toBeGreaterThan(0);
  });

  it('switches output profiles without creating a second preview component', async () => {
    const user = userEvent.setup();
    renderWithApp(<TemplateLabPage />, ['/template-lab']);

    await user.selectOptions(
      screen.getByRole('combobox', {name: '输出比例'}),
      'douyin_vertical',
    );

    expect(screen.getByText('1080×1920')).toBeInTheDocument();
    expect(screen.getAllByTestId('production-remotion-player')).toHaveLength(1);
  });
});
