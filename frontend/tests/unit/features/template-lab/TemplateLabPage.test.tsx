import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';

import {TemplateLabPage} from '@/features/template-lab/TemplateLabPage';
import {renderWithApp} from '@test/render';

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
      '/template-lab?template=world_warmth&version=1.1.0&scene=evidence_fullscreen&variant=evidence_documentary&profile=bilibili_horizontal&fixture=evidence-source-page&frame=0',
    ]);

    expect(
      screen.getByRole('heading', {name: '场景与视觉系统实验室'}),
    ).toBeInTheDocument();
    expect(screen.getByTestId('production-remotion-player')).toBeInTheDocument();
    expect(screen.getByText('1920×1080')).toBeInTheDocument();
    expect(screen.getByText('设计令牌')).toBeInTheDocument();
    expect(screen.getByText('视觉素材类型')).toBeInTheDocument();
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

    await user.selectOptions(
      screen.getByRole('combobox', {name: '已校验素材样本'}),
      'host-volunteers',
    );

    expect(screen.queryByTestId('production-remotion-player')).not.toBeInTheDocument();
    expect(screen.getByText('该场景状态不可预览')).toBeInTheDocument();
    expect(
      screen.getAllByText(/缺少真实 Live2D 预渲染 URL/u).length,
    ).toBeGreaterThan(0);
  });

  it('switches output profiles without creating a second preview component', async () => {
    const user = userEvent.setup();
    renderWithApp(<TemplateLabPage />, ['/template-lab']);

    await user.selectOptions(
      screen.getByRole('combobox', {name: '输出配置'}),
      'douyin_vertical',
    );

    expect(screen.getByText('1080×1920')).toBeInTheDocument();
    expect(screen.getAllByTestId('production-remotion-player')).toHaveLength(1);
  });

  it('preserves an unregistered future scene identifier for reproducible URLs', () => {
    renderWithApp(<TemplateLabPage />, ['/template-lab?scene=broll_video&fixture=broll-video-unavailable']);

    expect(screen.getByRole('status')).toHaveTextContent('该场景状态不可预览');
    expect(screen.getAllByText(/未知 fixture/u).length).toBeGreaterThan(0);
  });
});
