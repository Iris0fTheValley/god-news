import {Player} from '@remotion/player';
import {useQuery} from '@tanstack/react-query';
import {
  createTemplateLabFixture,
  GodNewsShortVideo,
  TEMPLATE_LAB_FIXTURES,
  worldWarmthTemplate,
  type EpisodeSceneModule,
  type OutputProfileId,
} from '@god-news/video/player';
import {Box, CheckCircle2, ExternalLink, MonitorPlay, ShieldCheck} from 'lucide-react';
import {useState} from 'react';
import {Link} from 'react-router-dom';

import {listVideoTemplates} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

const MODULE_LABELS: Record<EpisodeSceneModule, string> = {
  host_evidence: '主持人与证据',
  evidence_fullscreen: '全屏证据',
  source_video: '源视频',
  broll_video: '授权 B-roll',
};

const MODULE_DESCRIPTIONS: Record<EpisodeSceneModule, string> = {
  host_evidence: 'Live2D 预渲染主持人与新闻证据同屏，布局随横竖屏配置编译。',
  evidence_fullscreen: '让图片或网页证据占据主视觉，主持人按导演契约退场。',
  source_video: '播放已审核的原始视频，并保留原音、来源和翻译字幕。',
  broll_video: '使用已批准的外部补充画面，强制来源署名并默认静音。',
};

const profileConfig: Record<OutputProfileId, {width: number; height: number; label: string}> = {
  douyin_vertical: {width: 1080, height: 1920, label: '抖音 9:16'},
  bilibili_horizontal: {width: 1920, height: 1080, label: 'Bilibili 16:9'},
};

export function VisualModulesPage() {
  const [moduleId, setModuleId] = useState<EpisodeSceneModule>('evidence_fullscreen');
  const [profileId, setProfileId] = useState<OutputProfileId>('bilibili_horizontal');
  const templatesQuery = useQuery({
    queryKey: queryKeys.videoTemplates(),
    queryFn: listVideoTemplates,
  });
  const registryTemplate = templatesQuery.data?.find((template) => (
    template.template_id === worldWarmthTemplate.template_id
    && template.template_version === worldWarmthTemplate.template_version
  ));
  const registeredModules = registryTemplate?.capabilities.supported_modules ?? [];
  const variants = (registryTemplate?.scene_variants ?? []).filter(
    (variant) => variant.module_id === moduleId,
  );
  const [requestedVariantId, setRequestedVariantId] = useState('');
  const variantId = variants.some((variant) => variant.variant_id === requestedVariantId)
    ? requestedVariantId
    : variants[0]?.variant_id ?? '';
  const fixture = TEMPLATE_LAB_FIXTURES.find((candidate) => (
    candidate.moduleId === moduleId && candidate.variantId === variantId
  )) ?? TEMPLATE_LAB_FIXTURES.find((candidate) => candidate.moduleId === moduleId);
  const fixtureResult = (
    fixture === undefined
      ? null
      : createTemplateLabFixture({
          fixtureId: fixture.fixtureId,
          profileId,
          variantId,
        })
  );
  const selectedVariant = variants.find((variant) => variant.variant_id === variantId);
  const selectedProfile = profileConfig[profileId];
  const canPreview = fixtureResult?.available === true && fixtureResult.props !== null;
  const backendVariantIds = (registryTemplate?.scene_variants ?? [])
    .map((variant) => variant.variant_id)
    .sort()
    .join('|');
  const rendererVariantIds = [...worldWarmthTemplate.scene_variants]
    .map((variant) => variant.variant_id)
    .sort()
    .join('|');
  const registryParity = registryTemplate !== undefined
    && backendVariantIds === rendererVariantIds
    && registeredModules.join('|') === worldWarmthTemplate.capabilities.supported_modules.join('|');

  return (
    <div className="page visual-modules-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">VISUAL SYSTEM REGISTRY</p>
          <h1>视觉模块</h1>
          <p>这是生产渲染器的只读能力注册表，不是另一套模板。导演模型只能选择这里存在的模块与变体。</p>
        </div>
        <Link className="button primary" to={`/visual/scene-lab?scene=${moduleId}&variant=${variantId}&profile=${profileId}`}>
          在场景实验室检查 <ExternalLink size={15} aria-hidden="true" />
        </Link>
      </div>

      <div className="module-registry-summary">
        <div>
          <Box size={20} aria-hidden="true" />
          <span>生产模板</span>
          <strong>{worldWarmthTemplate.display_name}</strong>
        </div>
        <div>
          <ShieldCheck size={20} aria-hidden="true" />
          <span>跨语言契约</span>
          <strong>{registryParity ? '后端与渲染器一致' : '需要处理定义漂移'}</strong>
        </div>
        <div>
          <MonitorPlay size={20} aria-hidden="true" />
          <span>输出配置</span>
          <strong>{worldWarmthTemplate.capabilities.supported_profiles.length} 种</strong>
        </div>
      </div>

      {templatesQuery.error === null ? null : (
        <ApiErrorNotice error={templatesQuery.error} onRetry={() => void templatesQuery.refetch()} />
      )}
      {templatesQuery.isLoading ? (
        <div className="loading-state">正在读取生产模板注册表…</div>
      ) : registryTemplate === undefined ? (
        <div className="empty-state">
          <h2>后端没有注册当前生产模板</h2>
          <p>视觉目录停止展示，避免使用只存在于前端的虚假模块定义。</p>
        </div>
      ) : (
      <div className="visual-system-layout">
        <aside className="module-index" aria-label="视觉模块列表">
          <p className="eyebrow">MODULES</p>
          {registeredModules.map((candidate) => {
            const count = registryTemplate.scene_variants.filter(
              (variant) => variant.module_id === candidate,
            ).length;
            return (
              <button
                className={candidate === moduleId ? 'module-index-item active' : 'module-index-item'}
                type="button"
                key={candidate}
                onClick={() => {
                  setModuleId(candidate);
                  setRequestedVariantId('');
                }}
              >
                <span>
                  <strong>{MODULE_LABELS[candidate]}</strong>
                  <small>{candidate}</small>
                </span>
                <em>{count}</em>
              </button>
            );
          })}
        </aside>

        <section className="module-inspector">
          <div className="module-inspector-heading">
            <div>
              <p className="eyebrow">{moduleId}</p>
              <h2>{MODULE_LABELS[moduleId]}</h2>
              <p>{MODULE_DESCRIPTIONS[moduleId]}</p>
            </div>
            <span className="badge success"><CheckCircle2 size={14} aria-hidden="true" /> 已注册</span>
          </div>

          <div className="module-controls">
            <label className="field">
              <span>场景变体</span>
              <select className="select" value={variantId} onChange={(event) => setRequestedVariantId(event.target.value)}>
                {variants.map((variant) => (
                  <option key={variant.variant_id} value={variant.variant_id}>
                    {variant.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>输出比例</span>
              <select className="select" value={profileId} onChange={(event) => setProfileId(event.target.value as OutputProfileId)}>
                {Object.entries(profileConfig).map(([id, profile]) => (
                  <option key={id} value={id}>{profile.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className={`module-preview-frame ${profileId === 'douyin_vertical' ? 'vertical' : 'horizontal'}`}>
            {canPreview && fixtureResult?.props !== null ? (
              <Player
                component={GodNewsShortVideo}
                inputProps={fixtureResult.props}
                durationInFrames={180}
                compositionWidth={selectedProfile.width}
                compositionHeight={selectedProfile.height}
                fps={30}
                controls
                loop
                style={{width: '100%', height: '100%'}}
              />
            ) : (
              <div className="module-preview-unavailable">
                <MonitorPlay size={30} aria-hidden="true" />
                <h3>此模块需要真实生产素材</h3>
                <p>
                  {moduleId === 'host_evidence'
                    ? '主持人模块必须提供通过质量门的 Live2D 透明预渲染视频，系统不会用占位人物冒充预览。'
                    : moduleId === 'broll_video'
                      ? 'B-roll 必须先经过许可和人工审核，素材库目前没有可复用的测试片段。'
                      : fixtureResult?.diagnostics.join(' ') || '没有与该模块匹配的验证 fixture。'}
                </p>
              </div>
            )}
          </div>

          <div className="module-contract-grid">
            <div>
              <span>变体 ID</span>
              <strong>{selectedVariant?.variant_id ?? '—'}</strong>
            </div>
            <div>
              <span>支持比例</span>
              <strong>{selectedVariant?.supported_profiles.map((profile) => profileConfig[profile].label).join(' / ') ?? '—'}</strong>
            </div>
            <div>
              <span>主持人槽位</span>
              <strong>{selectedVariant?.supported_host_slots?.join(' / ') || '不显示主持人'}</strong>
            </div>
            <div>
              <span>画面素材</span>
              <strong>
                {selectedVariant === undefined
                  ? '—'
                  : `${selectedVariant.minimum_visual_assets}–${selectedVariant.maximum_visual_assets} 个`}
              </strong>
            </div>
          </div>
        </section>
      </div>
      )}
    </div>
  );
}
