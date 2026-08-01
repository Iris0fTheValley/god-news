import {Player} from '@remotion/player';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {
  createTemplateLabFixture,
  GodNewsShortVideo,
  TEMPLATE_LAB_FIXTURES,
  worldWarmthTemplate,
  type EpisodeSceneModule,
  type OutputProfileId,
} from '@god-news/video/player';
import {
  Box,
  CheckCircle2,
  ExternalLink,
  MonitorPlay,
  Power,
  ShieldCheck,
} from 'lucide-react';
import {useState} from 'react';
import {Link} from 'react-router-dom';

import {
  getVideoCapabilityRegistry,
  listVideoTemplates,
  setVideoCapabilityPolicy,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {VideoCapabilityView} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ModalDialog} from '../../components/ModalDialog';

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
  const queryClient = useQueryClient();
  const [moduleId, setModuleId] = useState<EpisodeSceneModule>('evidence_fullscreen');
  const [profileId, setProfileId] = useState<OutputProfileId>('bilibili_horizontal');
  const [policyTarget, setPolicyTarget] = useState<VideoCapabilityView | null>(null);
  const [policyReason, setPolicyReason] = useState('');
  const templatesQuery = useQuery({
    queryKey: queryKeys.videoTemplates(),
    queryFn: listVideoTemplates,
  });
  const registryQuery = useQuery({
    queryKey: queryKeys.videoRegistry(),
    queryFn: getVideoCapabilityRegistry,
  });
  const registryTemplate = templatesQuery.data?.find((template) => (
    template.template_id === worldWarmthTemplate.template_id
    && template.template_version === worldWarmthTemplate.template_version
  ));
  const registeredModules = registryTemplate?.capabilities.supported_modules ?? [];
  const moduleCapabilities = new Map(
    (registryQuery.data?.capabilities ?? [])
      .filter((item) => item.kind === 'module')
      .map((item) => [item.key.replace('module:', ''), item]),
  );
  const selectedCapability = moduleCapabilities.get(moduleId);
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
  const policyMutation = useMutation({
    mutationFn: (capability: VideoCapabilityView) => setVideoCapabilityPolicy({
      key: capability.key,
      enabled_for_new_batches: !capability.policy.enabled_for_new_batches,
      expected_version: capability.policy.version,
      reason: policyReason.trim(),
      operator_id: 'frontend-operator',
    }),
    onSuccess: async () => {
      setPolicyTarget(null);
      setPolicyReason('');
      await queryClient.invalidateQueries({queryKey: queryKeys.videoRegistry()});
    },
  });
  const error = templatesQuery.error ?? registryQuery.error ?? policyMutation.error;

  return (
    <div className="page visual-modules-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">VISUAL SYSTEM REGISTRY</p>
          <h1>视觉模块</h1>
          <p>这是生产渲染器的能力注册表。模块策略只影响新批次，已审核批次继续使用冻结快照。</p>
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

      {error === null ? null : (
        <ApiErrorNotice
          error={error}
          onRetry={() => {
            void templatesQuery.refetch();
            void registryQuery.refetch();
          }}
        />
      )}
      {templatesQuery.isLoading || registryQuery.isLoading ? (
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
            const capability = moduleCapabilities.get(candidate);
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
                <em title={`${capability?.usage_count ?? 0} 个批次使用`}>
                  {capability?.effective_enabled === false ? '停' : count}
                </em>
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
            <div className="module-policy-actions">
              <span className={`badge ${selectedCapability?.effective_enabled === false ? 'warning' : 'success'}`}>
                <CheckCircle2 size={14} aria-hidden="true" />
                {selectedCapability?.effective_enabled === false ? '新批次已停用' : '新批次可用'}
              </span>
              {selectedCapability === undefined ? null : (
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => {
                    setPolicyTarget(selectedCapability);
                    setPolicyReason('');
                  }}
                >
                  <Power size={15} aria-hidden="true" />
                  {selectedCapability.policy.enabled_for_new_batches ? '停用模块' : '启用模块'}
                </button>
              )}
            </div>
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
                acknowledgeRemotionLicense
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
            <div>
              <span>依赖位置</span>
              <strong>{selectedCapability?.used_by?.length ?? 0} 处注册表引用</strong>
            </div>
            <div>
              <span>历史使用</span>
              <strong>{selectedCapability?.usage_count ?? 0} 个视频批次</strong>
            </div>
            <div>
              <span>策略版本</span>
              <strong>v{selectedCapability?.policy.version ?? 1}</strong>
            </div>
            <div>
              <span>停用传播</span>
              <strong>
                {selectedCapability?.disabled_by?.length
                  ? selectedCapability.disabled_by.join(' / ')
                  : '无阻塞依赖'}
              </strong>
            </div>
          </div>
          {selectedCapability?.active_batch_ids?.length ? (
            <div className="module-usage-list">
              <p className="eyebrow">USAGE LOCATIONS</p>
              <div>
                {(selectedCapability.active_batch_ids ?? []).map((batchId) => (
                  <Link
                    key={batchId}
                    to={`/production/batches?batch=${encodeURIComponent(batchId)}`}
                  >
                    批次 {batchId.slice(0, 8)}
                  </Link>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      </div>
      )}
      <ModalDialog
        open={policyTarget !== null}
        className="create-drawer"
        labelledBy="module-policy-title"
        onClose={() => setPolicyTarget(null)}
      >
        <form
          className="panel-body form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            if (policyTarget !== null) policyMutation.mutate(policyTarget);
          }}
        >
          <div className="wide">
            <p className="eyebrow">NEW-BATCH POLICY</p>
            <h2 id="module-policy-title">
              {policyTarget?.policy.enabled_for_new_batches ? '停用视觉模块' : '启用视觉模块'}
            </h2>
            <p className="field-hint">
              变更只作用于之后创建的视频批次。已有批次保留完整模板快照，不会因实时策略改变而失去可复现性。
            </p>
          </div>
          <label className="field wide">
            <span>操作原因</span>
            <textarea
              className="textarea"
              required
              minLength={3}
              maxLength={500}
              value={policyReason}
              onChange={(event) => setPolicyReason(event.target.value)}
              placeholder="记录停用、维护或恢复的原因"
            />
          </label>
          <div className="form-actions wide">
            <button className="button" type="button" onClick={() => setPolicyTarget(null)}>取消</button>
            <button
              className="button primary"
              type="submit"
              disabled={policyMutation.isPending || policyReason.trim().length < 3}
            >
              {policyMutation.isPending ? '正在提交…' : '确认策略变更'}
            </button>
          </div>
        </form>
      </ModalDialog>
    </div>
  );
}
