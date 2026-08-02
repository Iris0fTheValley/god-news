import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {
  Archive,
  ExternalLink,
  Film,
  Image as ImageIcon,
  Library,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';

import {
  archiveMediaCatalogAsset,
  listStories,
  listMediaCatalogAssets,
  mediaCatalogAssetContentUrl,
  restoreMediaCatalogAsset,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {MediaCatalogEntry} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ModalDialog} from '../../components/ModalDialog';

type SourceFilter = 'all' | MediaCatalogEntry['source_kind'];
type KindFilter = 'all' | MediaCatalogEntry['media_kind'];
type LifecycleFilter = 'all' | MediaCatalogEntry['lifecycle'];

const SOURCE_LABELS: Record<MediaCatalogEntry['source_kind'], string> = {
  visual_asset: '编辑上传 / 网页截图',
  visual_discovery: 'Commons 授权素材',
  source_media: '来源视频证据',
};

const EDITORIAL_LABELS: Record<string, string> = {
  approved: '已批准',
  staged: '待审核',
  rejected: '已拒绝',
  superseded: '已替换',
  bound: '已绑定',
  publish_eligible: '可发布',
  rights_review: '待权利审核',
};

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '未下载';
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function formatDuration(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${(value / 1000).toFixed(1)} 秒`;
}

function AssetCard({
  asset,
  busy,
  onLifecycleChange,
}: {
  asset: MediaCatalogEntry;
  busy: boolean;
  onLifecycleChange: (asset: MediaCatalogEntry) => void;
}) {
  const previewUrl = asset.has_local_content
    ? mediaCatalogAssetContentUrl(asset.catalog_id)
    : asset.external_preview_url;
  const usages = asset.usages ?? [];
  const usageLabel = usages.length === 0
    ? '尚未使用'
    : `${usages.length} 条使用记录`;
  const groupedStoryReferences = asset.story_references ?? [];
  const storyReferences = groupedStoryReferences.length > 0
    ? groupedStoryReferences
    : [asset.story_id];
  const dimensions = asset.width && asset.height ? `${asset.width}×${asset.height}` : null;
  const duration = formatDuration(asset.duration_ms);
  return (
    <article className={`library-asset-card${asset.lifecycle === 'archived' ? ' archived' : ''}`}>
      <div className="library-asset-preview">
        {previewUrl === null || previewUrl === undefined ? (
          <div className="asset-preview-placeholder">
            {asset.media_kind === 'video'
              ? <Film size={30} aria-hidden="true" />
              : <ImageIcon size={30} aria-hidden="true" />}
            <span>素材尚未下载</span>
          </div>
        ) : asset.media_kind === 'video' ? (
          <video controls preload="metadata" src={previewUrl}>
            <track kind="captions" />
          </video>
        ) : (
          <img src={previewUrl} alt="" loading="lazy" />
        )}
        <span className={`asset-rights-state ${asset.selectable ? 'approved' : 'review'}`}>
          {asset.selectable
            ? <ShieldCheck size={13} aria-hidden="true" />
            : <ShieldAlert size={13} aria-hidden="true" />}
          {asset.lifecycle === 'archived'
            ? '已归档'
            : asset.selectable
              ? '可进入新制作'
              : '不可进入新制作'}
        </span>
      </div>
      <div className="library-asset-body">
        <div>
          <p className="eyebrow">{SOURCE_LABELS[asset.source_kind]}</p>
          <h3 title={asset.filename}>{asset.filename}</h3>
          <p>{asset.attribution || '项目内编辑素材'}</p>
        </div>
        <ul className="asset-metadata">
          <li>{asset.media_kind === 'video' ? '视频' : '图片'}</li>
          {dimensions === null ? null : <li>{dimensions}</li>}
          {duration === null ? null : <li>{duration}</li>}
          <li>{formatBytes(asset.size_bytes)}</li>
          <li>{asset.license_label || '项目内来源证据'}</li>
          <li>{EDITORIAL_LABELS[asset.editorial_state] || asset.editorial_state}</li>
          {(asset.content_occurrence_count ?? 1) > 1 ? (
            <li>{asset.content_occurrence_count} 个相同目录绑定</li>
          ) : null}
          <li>{storyReferences.length} 个故事引用</li>
        </ul>
        <details className="asset-usage-details">
          <summary>{usageLabel}</summary>
          {usages.length === 0 ? (
            <p>该素材尚未绑定故事或冻结到视频批次。</p>
          ) : (
            <ul>
              {usages.map((usage, index) => (
                <li key={`${usage.purpose}-${usage.batch_id ?? usage.story_id}-${index}`}>
                  <span>{usage.purpose === 'batch_scene' ? '视频场景' : '故事绑定'}</span>
                  <Link to={usage.batch_id
                    ? `/production/batches?batch=${encodeURIComponent(usage.batch_id)}`
                    : `/stories/${usage.story_id}`}
                  >
                    {usage.batch_id
                      ? `批次 ${usage.batch_id.slice(0, 8)} · 场景 ${(usage.scene_sequence ?? 0) + 1}`
                      : `故事 ${usage.story_id.slice(0, 8)}`}
                  </Link>
                  <small>{usage.state === 'frozen' ? '冻结证据' : '当前使用'}</small>
                </li>
              ))}
            </ul>
          )}
        </details>
        <div className="asset-card-actions">
          {asset.source_url === null || asset.source_url === undefined ? null : (
            <a className="button secondary" href={asset.source_url} target="_blank" rel="noreferrer">
              原始来源 <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
          <Link className="button secondary" to={`/stories/${storyReferences[0]}`}>
            故事工作台
          </Link>
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={() => onLifecycleChange(asset)}
          >
            {asset.lifecycle === 'active' ? (
              <><Archive size={15} aria-hidden="true" /> 归档</>
            ) : (
              <><RotateCcw size={15} aria-hidden="true" /> 恢复</>
            )}
          </button>
        </div>
      </div>
    </article>
  );
}

export function VisualAssetsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [source, setSource] = useState<SourceFilter>('all');
  const [kind, setKind] = useState<KindFilter>('all');
  const [lifecycle, setLifecycle] = useState<LifecycleFilter>('active');
  const [storyReference, setStoryReference] = useState('all');
  const [pendingAsset, setPendingAsset] = useState<MediaCatalogEntry | null>(null);
  const [reason, setReason] = useState('');
  const params = useMemo(() => ({
    search: search.trim() || undefined,
    source_kind: source === 'all' ? undefined : source,
    media_kind: kind === 'all' ? undefined : kind,
    lifecycle: lifecycle === 'all' ? undefined : lifecycle,
    story_id: storyReference === 'all' ? undefined : storyReference,
    limit: 200,
  }), [kind, lifecycle, search, source, storyReference]);
  const catalogQuery = useQuery({
    queryKey: [...queryKeys.mediaCatalog(), params],
    queryFn: () => listMediaCatalogAssets(params),
  });
  const lifecycleMutation = useMutation({
    mutationFn: (asset: MediaCatalogEntry) => {
      const body = {
        expected_version: asset.lifecycle_version,
        operator_id: 'frontend-operator',
        reason: reason.trim(),
      };
      return asset.lifecycle === 'active'
        ? archiveMediaCatalogAsset(asset.catalog_id, body)
        : restoreMediaCatalogAsset(asset.catalog_id, body);
    },
    onSuccess: async () => {
      setPendingAsset(null);
      setReason('');
      await queryClient.invalidateQueries({queryKey: queryKeys.mediaCatalog()});
    },
  });
  const storiesQuery = useQuery({
    queryKey: queryKeys.stories(),
    queryFn: () => listStories(),
  });
  const items = catalogQuery.data?.items ?? [];
  const selectableCount = items.filter((item) => item.selectable).length;
  const archivedCount = items.filter((item) => item.lifecycle === 'archived').length;
  const error = catalogQuery.error ?? lifecycleMutation.error;

  return (
    <div className="page library-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">GLOBAL MEDIA CATALOG</p>
          <h1>画面素材库</h1>
          <p>统一检索图片与视频，核对来源、权利、故事绑定和成片使用记录。归档只阻止新制作继续选用，不删除历史证据或文件。</p>
        </div>
      </div>

      {error === null ? null : <ApiErrorNotice error={error} />}
      <div className="library-layout">
        <aside className="library-filter-rail" aria-label="素材筛选">
          <div>
            <p className="eyebrow">FILTER</p>
            <h2>筛选素材</h2>
          </div>
          <label className="search-control library-search">
            <Search size={16} aria-hidden="true" />
            <input
              className="input"
              type="search"
              placeholder="文件、作者、许可或来源"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="搜索画面素材"
            />
          </label>
          <label className="field">
            <span>故事引用</span>
            <select className="select" value={storyReference} onChange={(event) => setStoryReference(event.target.value)}>
              <option value="all">全部故事</option>
              {(storiesQuery.data ?? []).filter(
                (story): story is typeof story & {story_id: string} => story.story_id !== undefined,
              ).map((story) => (
                <option key={story.story_id} value={story.story_id}>
                  {story.title || story.source.title || '未命名故事'}
                  {' · '}
                  {story.story_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>来源</span>
            <select className="select" value={source} onChange={(event) => setSource(event.target.value as SourceFilter)}>
              <option value="all">全部来源</option>
              <option value="visual_asset">编辑上传 / 网页截图</option>
              <option value="visual_discovery">Commons</option>
              <option value="source_media">来源视频</option>
            </select>
          </label>
          <label className="field">
            <span>媒介</span>
            <select className="select" value={kind} onChange={(event) => setKind(event.target.value as KindFilter)}>
              <option value="all">图片与视频</option>
              <option value="image">图片</option>
              <option value="video">视频</option>
            </select>
          </label>
          <label className="field">
            <span>生命周期</span>
            <select className="select" value={lifecycle} onChange={(event) => setLifecycle(event.target.value as LifecycleFilter)}>
              <option value="active">使用中</option>
              <option value="archived">已归档</option>
              <option value="all">全部</option>
            </select>
          </label>
          <button
            className="button ghost"
            type="button"
            onClick={() => {
              setSearch('');
              setSource('all');
              setKind('all');
              setLifecycle('active');
              setStoryReference('all');
            }}
          >
            重置筛选
          </button>
        </aside>
        <section className="library-results" aria-label="素材结果">
          {catalogQuery.isLoading ? (
            <div className="asset-library-grid" aria-label="正在加载画面素材">
              {[0, 1, 2].map((item) => <div className="library-asset-card skeleton-card" key={item} />)}
            </div>
          ) : items.length === 0 ? (
            <div className="empty-state">
              <Library size={28} aria-hidden="true" />
              <h2>没有符合条件的素材</h2>
              <p>调整筛选条件，或在故事工作台上传画面、审核 Commons 素材、采集来源视频。</p>
            </div>
          ) : (
            <>
              <div className="library-summary" aria-live="polite">
                <strong>{catalogQuery.data?.total ?? items.length}</strong> 个唯一素材
                <span>{selectableCount} 个可进入新制作</span>
                <span>{archivedCount} 个已归档</span>
              </div>
              <div className="asset-library-grid">
                {items.map((asset) => (
                  <AssetCard
                    asset={asset}
                    busy={lifecycleMutation.isPending}
                    key={asset.catalog_id}
                    onLifecycleChange={(item) => {
                      setPendingAsset(item);
                      setReason('');
                    }}
                  />
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      <ModalDialog
        open={pendingAsset !== null}
        className="create-drawer"
        labelledBy="asset-lifecycle-title"
        onClose={() => setPendingAsset(null)}
      >
        <form
          className="panel-body form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            if (pendingAsset !== null) lifecycleMutation.mutate(pendingAsset);
          }}
        >
          <div className="wide">
            <p className="eyebrow">RECOVERABLE LIFECYCLE</p>
            <h2 id="asset-lifecycle-title">
              {pendingAsset?.lifecycle === 'active' ? '归档素材' : '恢复素材'}
            </h2>
            <p className="field-hint">
              {pendingAsset?.lifecycle === 'active'
                ? '归档后新视频批次不会再选用该素材；现有故事绑定、历史批次和审计证据保持可查。'
                : '恢复前后端会重新核对文件大小与 SHA-256，发现缺失或篡改会拒绝恢复。'}
            </p>
          </div>
          <label className="field wide">
            <span>操作原因</span>
            <textarea
              className="textarea"
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="记录本次生命周期变更的原因"
            />
          </label>
          <div className="form-actions wide">
            <button className="button" type="button" onClick={() => setPendingAsset(null)}>取消</button>
            <button className="button primary" type="submit" disabled={lifecycleMutation.isPending || reason.trim().length < 3}>
              {lifecycleMutation.isPending ? '正在提交…' : '确认变更'}
            </button>
          </div>
        </form>
      </ModalDialog>
    </div>
  );
}
