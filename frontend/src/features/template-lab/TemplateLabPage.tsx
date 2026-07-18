import {
  buildRenderPlan,
  compileSceneLayout,
  createTemplateLabFixture,
  GodNewsShortVideo,
  rectStyle,
  TEMPLATE_LAB_FIXTURES,
  worldWarmthTemplate,
  type GodNewsVideoProps,
} from '@god-news/video/player';
import {Player, type PlayerRef} from '@remotion/player';
import {
  AlertTriangle,
  ChevronFirst,
  ChevronLast,
  Clipboard,
  Download,
  Image,
  Pause,
  Play,
  ScanLine,
  StepBack,
  StepForward,
} from 'lucide-react';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useSearchParams} from 'react-router-dom';

import {
  readTemplateLabState,
  writeTemplateLabState,
  type TemplateLabState,
} from './templateLabState';

const templates = [worldWarmthTemplate] as const;
const overlayOptions = [
  ['safeArea', '安全区'],
  ['assetBounds', '素材边界'],
  ['hostBounds', '主持人槽位'],
  ['captionBounds', '字幕区域'],
] as const satisfies ReadonlyArray<
  readonly [
    'safeArea' | 'assetBounds' | 'hostBounds' | 'captionBounds',
    string,
  ]
>;

const rectangleStyle = (
  rect: ReturnType<typeof compileSceneLayout>['safeArea'],
): React.CSSProperties => ({
  position: 'absolute',
  ...rectStyle(rect),
});

const downloadJson = (props: GodNewsVideoProps): void => {
  const blob = new Blob([`${JSON.stringify(props, null, 2)}\n`], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `template-lab-${props.template?.template_id ?? 'fixture'}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
};

export function TemplateLabPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => readTemplateLabState(searchParams), [searchParams]);
  const playerRef = useRef<PlayerRef>(null);
  const [currentFrame, setCurrentFrame] = useState(state.frame);
  const [playing, setPlaying] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const updateState = useCallback(
    (patch: Partial<TemplateLabState>) => {
      const next = {...state, ...patch};
      setSearchParams(writeTemplateLabState(next), {replace: true});
    },
    [setSearchParams, state],
  );

  const template =
    templates.find(
      (candidate) =>
        candidate.template_id === state.template &&
        candidate.template_version === state.version,
    ) ?? worldWarmthTemplate;
  const variants = template.scene_variants.filter(
    (variant) => variant.module_id === state.scene,
  );
  const selectedFixture =
    TEMPLATE_LAB_FIXTURES.find((fixture) => fixture.fixtureId === state.fixture) ??
    null;
  const fixtureResult = useMemo(
    () =>
      createTemplateLabFixture({
        fixtureId: state.fixture,
        profileId: state.profile,
        variantId: state.variant,
        title: state.title || undefined,
        translatedCaption: state.caption || undefined,
        hostVisible: state.hostVisible,
        hostSlot: state.hostSlot,
        hostVideoUrl: state.hostVideoUrl || undefined,
        tokenPreset: state.tokenPreset,
      }),
    [
      state.caption,
      state.fixture,
      state.hostSlot,
      state.hostVideoUrl,
      state.hostVisible,
      state.profile,
      state.title,
      state.tokenPreset,
      state.variant,
    ],
  );
  const props = fixtureResult.props;
  const profile = props?.output_profiles.find(
    (candidate) => candidate.profile_id === state.profile,
  );
  const plan = props && profile ? buildRenderPlan(props, profile.fps) : null;
  const durationInFrames = plan?.durationInFrames ?? 1;
  const safeFrame = Math.min(durationInFrames - 1, Math.max(0, state.frame));
  const scene = props?.episode_plan?.scenes.find(
    (candidate) => candidate.module_id === state.scene,
  );
  const layout = props && scene ? compileSceneLayout(props, scene) : null;
  const activeVariant = scene?.variant_id ?? null;
  const activeAsset = props?.visual_assets[0];
  const captionText =
    state.caption ||
    selectedFixture?.translatedCaption ||
    fixtureResult.fixture?.translatedCaption ||
    '';
  const titleText =
    state.title || selectedFixture?.title || fixtureResult.fixture?.title || '';

  useEffect(() => {
    const player = playerRef.current;
    if (!player || !fixtureResult.available) return;
    player.seekTo(safeFrame);
    setCurrentFrame(safeFrame);
  }, [fixtureResult.available, props, safeFrame]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const onFrame = (event: {detail: {frame: number}}) => {
      setCurrentFrame(event.detail.frame);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => {
      setPlaying(false);
      updateState({frame: player.getCurrentFrame()});
    };
    const onEnded = () => {
      setPlaying(false);
      updateState({frame: player.getCurrentFrame()});
    };
    player.addEventListener('frameupdate', onFrame);
    player.addEventListener('play', onPlay);
    player.addEventListener('pause', onPause);
    player.addEventListener('ended', onEnded);
    return () => {
      player.removeEventListener('frameupdate', onFrame);
      player.removeEventListener('play', onPlay);
      player.removeEventListener('pause', onPause);
      player.removeEventListener('ended', onEnded);
    };
  }, [props, updateState]);

  const seekTo = (frame: number) => {
    const clamped = Math.min(durationInFrames - 1, Math.max(0, Math.round(frame)));
    playerRef.current?.seekTo(clamped);
    setCurrentFrame(clamped);
    updateState({frame: clamped});
  };

  const pauseAtCurrentFrame = () => {
    const player = playerRef.current;
    if (!player) return;
    player.pause();
    const frozenFrame = player.getCurrentFrame();
    // Remotion's pause event can race the underlying HTMLVideoElement by one
    // decoded frame. Seeking to the committed frame makes pause a true media
    // barrier for frame-accurate review instead of only stopping the clock.
    player.seekTo(frozenFrame);
    setCurrentFrame(frozenFrame);
    updateState({frame: frozenFrame});
  };

  const changeScene = (nextScene: TemplateLabState['scene']) => {
    const nextFixture = TEMPLATE_LAB_FIXTURES.find(
      (fixture) => fixture.moduleId === nextScene,
    );
    const nextVariant = template.default_scene_variants[nextScene] ?? '';
    updateState({
      scene: nextScene,
      variant: nextVariant,
      fixture: nextFixture?.fixtureId ?? `${nextScene}-unavailable`,
      hostVisible: nextScene === 'host_evidence',
      hostSlot: nextVariant === 'host_corner_full_bleed' ? 'corner' : 'primary',
      title: '',
      caption: '',
      frame: 0,
    });
  };

  const changeFixture = (fixtureId: string) => {
    const fixture = TEMPLATE_LAB_FIXTURES.find(
      (candidate) => candidate.fixtureId === fixtureId,
    );
    if (!fixture) return;
    updateState({
      fixture: fixture.fixtureId,
      scene: fixture.moduleId,
      variant: fixture.variantId,
      hostVisible: fixture.moduleId === 'host_evidence',
      hostSlot: fixture.variantId === 'host_corner_full_bleed' ? 'corner' : 'primary',
      title: '',
      caption: '',
      frame: 0,
    });
  };

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setNotice('可复现预览 URL 已复制。');
    } catch {
      setNotice('浏览器拒绝剪贴板访问，请从地址栏复制当前 URL。');
    }
  };

  const copyDevelopmentCommand = async (
    command: string,
    successMessage: string,
  ) => {
    try {
      await navigator.clipboard.writeText(command);
      setNotice(successMessage);
    } catch {
      setNotice(`浏览器拒绝剪贴板访问，请手动运行：${command}`);
    }
  };

  return (
    <div className="page template-lab-page">
      <div className="page-heading template-lab-heading">
        <div>
          <p className="eyebrow">PRODUCTION COMPONENT HARNESS</p>
          <h1>模板实验室</h1>
          <p>使用生产 Remotion Composition、模板快照、布局编译和场景注册表进行可复现验收。</p>
        </div>
        <div className="template-lab-heading-actions">
          <button
            className="button secondary"
            type="button"
            onClick={() => void copyUrl()}
          >
            <Clipboard size={16} aria-hidden="true" /> 复制预览 URL
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={props === null}
            onClick={() => {
              if (props) downloadJson(props);
            }}
          >
            <Download size={16} aria-hidden="true" /> 导出 validated props
          </button>
        </div>
      </div>

      {notice ? <p className="pending-note" role="status">{notice}</p> : null}

      <div className="template-lab-grid">
        <aside className="template-lab-panel template-lab-catalog" aria-label="模板目录">
          <p className="eyebrow">CATALOG</p>
          <h2>选择器</h2>
          <label className="field">
            <span>模板</span>
            <select className="select" value={state.template} disabled>
              <option value={template.template_id}>{template.display_name}</option>
            </select>
          </label>
          <label className="field">
            <span>模板版本</span>
            <select className="select" value={state.version} disabled>
              <option value={template.template_version}>{template.template_version}</option>
            </select>
          </label>
          <label className="field">
            <span>场景模块</span>
            <select
              className="select"
              value={state.scene}
              onChange={(event) => changeScene(event.target.value as TemplateLabState['scene'])}
            >
              {template.capabilities.supported_modules.map((moduleId) => (
                <option key={moduleId} value={moduleId}>{moduleId}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>场景变体</span>
            <select
              className="select"
              value={state.variant}
              disabled={variants.length === 0}
              onChange={(event) => updateState({
                variant: event.target.value,
                hostSlot:
                  event.target.value === 'host_corner_full_bleed' ? 'corner' : state.hostSlot,
                frame: 0,
              })}
            >
              {variants.map((variant) => (
                <option key={variant.variant_id} value={variant.variant_id}>
                  {variant.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>输出比例</span>
            <select
              className="select"
              value={state.profile}
              onChange={(event) => updateState({
                profile: event.target.value as TemplateLabState['profile'],
                frame: 0,
              })}
            >
              <option value="douyin_vertical">抖音 9:16</option>
              <option value="bilibili_horizontal">Bilibili 16:9</option>
            </select>
          </label>
          <label className="field">
            <span>Fixture</span>
            <select
              className="select"
              value={state.fixture}
              onChange={(event) => changeFixture(event.target.value)}
            >
              {TEMPLATE_LAB_FIXTURES.map((fixture) => (
                <option key={fixture.fixtureId} value={fixture.fixtureId}>
                  {fixture.displayName}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>主持人槽位</span>
            <select
              className="select"
              value={state.hostSlot}
              disabled={!state.hostVisible}
              onChange={(event) => updateState({
                hostSlot: event.target.value as TemplateLabState['hostSlot'],
                variant:
                  event.target.value === 'corner'
                    ? 'host_corner_full_bleed'
                    : 'host_split_editorial',
              })}
            >
              <option value="primary">primary</option>
              <option value="corner">corner</option>
            </select>
          </label>
          <label className="field">
            <span>设计令牌预设</span>
            <select
              className="select"
              value={state.tokenPreset}
              onChange={(event) => updateState({
                tokenPreset: event.target.value as TemplateLabState['tokenPreset'],
              })}
            >
              <option value="default">默认温暖编辑</option>
              <option value="high_contrast">高对比验收</option>
            </select>
          </label>
        </aside>

        <main className="template-lab-stage" aria-label="真实 Remotion 预览">
          <div className="template-lab-stage-toolbar">
            <div className="template-lab-playback">
              <button
                className="icon-button"
                type="button"
                data-testid="template-lab-play-pause"
                disabled={!fixtureResult.available}
                aria-label={playing ? '暂停' : '播放'}
                onClick={() => {
                  if (playing) pauseAtCurrentFrame();
                  else playerRef.current?.play();
                }}
              >
                {playing ? <Pause size={17} /> : <Play size={17} />}
              </button>
              <button className="icon-button" type="button" disabled={!fixtureResult.available} aria-label="首帧" onClick={() => seekTo(0)}>
                <ChevronFirst size={17} />
              </button>
              <button className="icon-button" type="button" data-testid="template-lab-previous-frame" disabled={!fixtureResult.available} aria-label="上一帧" onClick={() => seekTo(currentFrame - 1)}>
                <StepBack size={17} />
              </button>
              <button className="icon-button" type="button" data-testid="template-lab-next-frame" disabled={!fixtureResult.available} aria-label="下一帧" onClick={() => seekTo(currentFrame + 1)}>
                <StepForward size={17} />
              </button>
              <button className="icon-button" type="button" disabled={!fixtureResult.available} aria-label="末帧" onClick={() => seekTo(durationInFrames - 1)}>
                <ChevronLast size={17} />
              </button>
              <span className="metadata" data-testid="template-lab-current-frame">FRAME {currentFrame} / {durationInFrames - 1}</span>
            </div>
            <label className="template-lab-zoom">
              <span>缩放 {Math.round(state.zoom * 100)}%</span>
              <input
                type="range"
                min="0.2"
                max="0.8"
                step="0.05"
                value={state.zoom}
                onChange={(event) => updateState({zoom: Number(event.target.value)})}
              />
            </label>
          </div>

          <div className="template-lab-keyframes" aria-label="关键帧">
            {[0, Math.round((durationInFrames - 1) / 2), durationInFrames - 1].map(
              (frame, index) => (
                <button
                  className="button secondary compact-button"
                  type="button"
                  key={`${String(index)}-${String(frame)}`}
                  disabled={!fixtureResult.available}
                  onClick={() => seekTo(frame)}
                >
                  {index === 0 ? '开始' : index === 1 ? '中点' : '结束'} · {frame}
                </button>
              ),
            )}
          </div>

          <div className="template-lab-canvas">
            {props && profile && fixtureResult.available ? (
              <div
                className="template-lab-player-frame"
                data-testid="template-lab-player-frame"
                style={{
                  width: `${Math.round(profile.width * state.zoom)}px`,
                  aspectRatio: `${profile.width} / ${profile.height}`,
                }}
              >
                <Player
                  key={`${state.fixture}-${state.variant}-${state.profile}-${state.tokenPreset}`}
                  ref={playerRef}
                  component={GodNewsShortVideo}
                  inputProps={props}
                  durationInFrames={durationInFrames}
                  compositionWidth={profile.width}
                  compositionHeight={profile.height}
                  fps={profile.fps}
                  initialFrame={safeFrame}
                  controls={false}
                  clickToPlay={false}
                  acknowledgeRemotionLicense
                  initiallyMuted
                  style={{width: '100%', height: '100%'}}
                  errorFallback={({error}: {error: Error}) => (
                    <div className="template-lab-player-error" role="alert">
                      <AlertTriangle size={24} />
                      <strong>生产组件渲染失败</strong>
                      <span>{error.message}</span>
                    </div>
                  )}
                />
                {layout ? (
                  <div className="template-lab-overlays" aria-hidden="true">
                    {state.safeArea ? <div className="lab-boundary safe-boundary" style={rectangleStyle(layout.safeArea)}><span>SAFE AREA</span></div> : null}
                    {state.assetBounds ? <div className="lab-boundary asset-boundary" style={rectangleStyle(layout.media)}><span>ASSET</span></div> : null}
                    {state.hostBounds && layout.host ? <div className="lab-boundary host-boundary" style={rectangleStyle(layout.host)}><span>HOST</span></div> : null}
                    {state.captionBounds ? <div className="lab-boundary caption-boundary" style={rectangleStyle(layout.caption)}><span>CAPTION</span></div> : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="template-lab-unavailable" role="status">
                <AlertTriangle size={28} />
                <h3>该状态不可预览</h3>
                {fixtureResult.diagnostics.map((diagnostic) => (
                  <p key={diagnostic}>{diagnostic}</p>
                ))}
              </div>
            )}
          </div>
        </main>

        <aside className="template-lab-panel template-lab-inspector" aria-label="属性和诊断">
          <p className="eyebrow">INSPECTOR</p>
          <h2>属性与诊断</h2>
          <label className="field">
            <span>节目标题</span>
            <textarea
              className="textarea compact"
              value={titleText}
              maxLength={240}
              onChange={(event) => updateState({title: event.target.value})}
            />
          </label>
          <label className="field">
            <span>中文字幕</span>
            <textarea
              className="textarea"
              value={captionText}
              onChange={(event) => updateState({caption: event.target.value})}
            />
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={state.hostVisible}
              onChange={(event) => {
                if (event.target.checked) {
                  changeFixture('host-volunteers');
                } else {
                  updateState({
                    hostVisible: false,
                    scene: 'evidence_fullscreen',
                    variant: 'evidence_documentary',
                    frame: 0,
                  });
                }
              }}
            />
            <span>显示真实主持人</span>
          </label>
          <label className="field">
            <span>Live2D 预渲染浏览器 URL</span>
            <input
              className="input"
              type="url"
              placeholder="未提供时主持人 fixture 明确不可用"
              value={state.hostVideoUrl}
              disabled={!state.hostVisible}
              onChange={(event) => updateState({hostVideoUrl: event.target.value})}
            />
          </label>

          <fieldset className="template-lab-overlay-controls">
            <legend>诊断覆盖层</legend>
            {overlayOptions.map(([key, label]) => (
              <label className="checkbox-field" key={key}>
                <input
                  type="checkbox"
                  checked={state[key]}
                  onChange={(event) => updateState({
                    [key]: event.target.checked,
                  })}
                />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>

          <dl className="template-lab-diagnostics">
            <div><dt>模板</dt><dd>{template.template_id}@{template.template_version}</dd></div>
            <div><dt>场景模块</dt><dd>{scene?.module_id ?? state.scene}</dd></div>
            <div><dt>场景变体</dt><dd>{activeVariant ?? state.variant}</dd></div>
            <div><dt>输出配置</dt><dd>{state.profile}</dd></div>
            <div><dt>分辨率</dt><dd>{profile ? `${profile.width}×${profile.height}` : '不可用'}</dd></div>
            <div><dt>FPS</dt><dd>{profile?.fps ?? '—'}</dd></div>
            <div><dt>素材 ID</dt><dd>{activeAsset?.asset_id ?? '不可用'}</dd></div>
            <div><dt>素材类型</dt><dd>{activeAsset?.asset_type ?? '不可用'}</dd></div>
            <div><dt>当前帧</dt><dd>{currentFrame}</dd></div>
          </dl>

          {fixtureResult.diagnostics.length > 0 ? (
            <div className="template-lab-warning-list">
              {fixtureResult.diagnostics.map((diagnostic) => (
                <p key={diagnostic}><AlertTriangle size={15} /> {diagnostic}</p>
              ))}
            </div>
          ) : <p className="template-lab-ready">生产 Schema 与模板能力检查通过。</p>}

          <div className="template-lab-dev-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                const encodedUrl = window.btoa(window.location.href);
                void copyDevelopmentCommand(
                  `pnpm --dir frontend capture:template-lab -- --url-base64 "${encodedUrl}" --output "../outputs/template-lab/manual-frame-${currentFrame}.png"`,
                  '真实 Edge 截图命令已复制。',
                );
              }}
            >
              <Image size={16} /> 复制当前帧截图命令
            </button>
            <button
              className="button secondary"
              type="button"
              onClick={() =>
                void copyDevelopmentCommand(
                  'pnpm --dir frontend exec playwright test --project=desktop template-lab.visual.spec.ts',
                  '真实浏览器视觉回归命令已复制。',
                )
              }
            >
              <ScanLine size={16} /> 复制视觉回归命令
            </button>
            <p className="field-hint">命令使用 Microsoft Edge 加载当前生产 Remotion Player；浏览器错误、媒体解码失败或字幕实际溢出会使视觉回归失败。</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
