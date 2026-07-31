import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {
  ExternalLink,
  FileImage,
  Film,
  Image as ImageIcon,
  Search,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';

import {
  listSourceMediaArtifacts,
  listStories,
  listStoryVisualAssets,
  listStoryVisualDiscoveryAssets,
  approveVisualDiscoveryAsset,
  rejectVisualDiscoveryAsset,
  reuseApprovedVisualDiscoveryAsset,
  sourceMediaContentUrl,
  visualAssetContentUrl,
  visualDiscoveryAssetContentUrl,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {
  SourceMediaArtifact,
  Story,
  VisualAsset,
  VisualDiscoveryAssetView,
} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ModalDialog} from '../../components/ModalDialog';

type LibraryKind = 'all' | 'story' | 'commons' | 'source-video';

interface LibraryAsset {
  id: string;
  kind: Exclude<LibraryKind, 'all'>;
  label: string;
  detail: string;
  contentUrl: string;
  sourceUrl: string | null;
  status: 'approved' | 'review' | 'bound' | 'rejected' | 'superseded';
  metadata: string[];
  discoveryAsset?: VisualDiscoveryAssetView;
}

function storyLabel(story: Story): string {
  return story.title?.trim() || story.source.title || '未命名故事';
}

function visualAssetItem(asset: VisualAsset): LibraryAsset | null {
  if (asset.asset_id === undefined) return null;
  return {
    id: asset.asset_id,
    kind: 'story',
    label: asset.filename,
    detail: asset.origin === 'source_page_screenshot' ? '来源网页截图' : '编辑上传素材',
    contentUrl: visualAssetContentUrl(asset.story_id, asset.asset_id),
    sourceUrl: null,
    status: 'bound',
    metadata: [
      asset.content_type,
      `${(asset.size_bytes / 1024).toFixed(0)} KiB`,
      asset.segment_id === null || asset.segment_id === undefined ? '故事级' : '已绑定脚本段',
    ],
  };
}

function discoveryAssetItem(asset: VisualDiscoveryAssetView): LibraryAsset {
  const rights = asset.candidate.rights;
  const status = asset.status === 'staged' ? 'review' : asset.status;
  const statusLabel = {
    approved: '已批准',
    rejected: '已拒绝',
    staged: '待审核',
    superseded: '已替代',
  }[asset.status];
  return {
    id: asset.asset_id,
    kind: 'commons',
    label: asset.candidate.file_title,
    detail: asset.candidate.attribution.author || asset.candidate.attribution.attribution_text,
    contentUrl: asset.status === 'approved'
      ? visualDiscoveryAssetContentUrl(asset.asset_id)
      : asset.candidate.direct_download_url,
    sourceUrl: asset.candidate.canonical_page_url,
    status,
    metadata: [
      `${asset.candidate.width}×${asset.candidate.height}`,
      rights.source_license_label || rights.license,
      statusLabel,
      `脚本段 ${asset.segment_id.slice(0, 8)}`,
    ],
    discoveryAsset: asset,
  };
}

function sourceMediaItem(asset: SourceMediaArtifact): LibraryAsset {
  return {
    id: asset.artifact_id ?? `${asset.story_id}-${String(asset.media_index)}`,
    kind: 'source-video',
    label: asset.filename,
    detail: asset.attribution.author || asset.attribution.publisher || asset.source,
    contentUrl: sourceMediaContentUrl(asset.story_id, asset.artifact_id ?? ''),
    sourceUrl: asset.source_url,
    status: asset.publish_eligible ? 'approved' : 'review',
    metadata: [
      `${asset.probe.width}×${asset.probe.height}`,
      `${(asset.probe.duration_ms / 1000).toFixed(1)} 秒`,
      asset.publish_eligible ? '可进入发布流程' : '仅供审核',
    ],
  };
}

function AssetPreview({
  asset,
  busy,
  onApprove,
  onReject,
  onReuse,
}: {
  asset: LibraryAsset;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onReuse: () => void;
}) {
  const isVideo = asset.kind === 'source-video';
  return (
    <article className="library-asset-card">
      <div className="library-asset-preview">
        {isVideo ? (
          <video controls preload="metadata" src={asset.contentUrl}>
            <track kind="captions" />
          </video>
        ) : (
          <img src={asset.contentUrl} alt="" loading="lazy" />
        )}
        <span className={`asset-rights-state ${asset.status}`}>
          {asset.status === 'approved' ? (
            <ShieldCheck size={13} aria-hidden="true" />
          ) : asset.status === 'review' || asset.status === 'rejected' ? (
            <ShieldAlert size={13} aria-hidden="true" />
          ) : (
            <FileImage size={13} aria-hidden="true" />
          )}
          {asset.status === 'approved'
            ? '可用于制作'
            : asset.status === 'review'
              ? '待权利审核'
              : asset.status === 'rejected'
                ? '已拒绝'
                : asset.status === 'superseded'
                  ? '已替代'
                  : '已绑定'}
        </span>
      </div>
      <div className="library-asset-body">
        <div>
          <p className="eyebrow">{asset.kind.replace('-', ' ')}</p>
          <h3 title={asset.label}>{asset.label}</h3>
          <p>{asset.detail}</p>
        </div>
        <ul className="asset-metadata">
          {asset.metadata.map((item) => <li key={item}>{item}</li>)}
        </ul>
        {asset.sourceUrl === null ? null : (
          <a href={asset.sourceUrl} target="_blank" rel="noreferrer">
            查看原始来源 <ExternalLink size={14} aria-hidden="true" />
          </a>
        )}
        {asset.discoveryAsset === undefined ? null : (
          <div className="asset-card-actions">
            {asset.discoveryAsset.status === 'staged' ? (
              <>
                <button className="button secondary" type="button" disabled={busy} onClick={onReject}>
                  拒绝
                </button>
                <button className="button primary" type="button" disabled={busy} onClick={onApprove}>
                  批准素材
                </button>
              </>
            ) : asset.discoveryAsset.status === 'approved' ? (
              <button className="button" type="button" disabled={busy} onClick={onReuse}>
                复用到其他故事
              </button>
            ) : null}
          </div>
        )}
      </div>
    </article>
  );
}

export function VisualAssetsPage() {
  const queryClient = useQueryClient();
  const [storyId, setStoryId] = useState('');
  const [kind, setKind] = useState<LibraryKind>('all');
  const [search, setSearch] = useState('');
  const [reuseAssetId, setReuseAssetId] = useState<string | null>(null);
  const [reuseStoryId, setReuseStoryId] = useState('');
  const [reuseSegmentId, setReuseSegmentId] = useState('');
  const storiesQuery = useQuery({
    queryKey: queryKeys.stories(),
    queryFn: () => listStories(),
  });
  const allStories = storiesQuery.data ?? [];
  const stories = allStories.filter((story) => story.script !== null && story.script !== undefined);
  const effectiveStoryId = storyId || stories[0]?.story_id || '';

  const storyAssetsQuery = useQuery({
    queryKey: queryKeys.visualAssets(effectiveStoryId),
    queryFn: () => listStoryVisualAssets(effectiveStoryId),
    enabled: effectiveStoryId !== '',
  });
  const discoveryQuery = useQuery({
    queryKey: queryKeys.visualDiscoveryAssets(effectiveStoryId),
    queryFn: () => listStoryVisualDiscoveryAssets(effectiveStoryId),
    enabled: effectiveStoryId !== '',
  });
  const sourceMediaQuery = useQuery({
    queryKey: queryKeys.sourceMedia(effectiveStoryId),
    queryFn: () => listSourceMediaArtifacts(effectiveStoryId),
    enabled: effectiveStoryId !== '',
  });

  const assets = useMemo(() => {
    const storyAssets = storyAssetsQuery.data;
    const uploaded = [
      storyAssets?.source_page_screenshot,
      ...(storyAssets?.segment_assets ?? []).map((binding) => binding.asset),
    ].flatMap((asset) => {
      if (asset === null || asset === undefined) return [];
      const item = visualAssetItem(asset);
      return item === null ? [] : [item];
    });
    return [
      ...uploaded,
      ...(discoveryQuery.data ?? []).map(discoveryAssetItem),
      ...(sourceMediaQuery.data ?? []).map(sourceMediaItem),
    ];
  }, [discoveryQuery.data, sourceMediaQuery.data, storyAssetsQuery.data]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const visibleAssets = assets.filter((asset) => (
    (kind === 'all' || asset.kind === kind)
    && (normalizedSearch === ''
      || [asset.label, asset.detail, ...asset.metadata]
        .some((value) => value.toLocaleLowerCase().includes(normalizedSearch)))
  ));
  const selectedStory = stories.find((story) => story.story_id === effectiveStoryId);
  const targetStory = stories.find((story) => story.story_id === (
    reuseStoryId || stories.find((story) => story.story_id !== effectiveStoryId)?.story_id
  ));
  const targetSegments = targetStory?.script?.segments ?? [];
  const effectiveReuseSegmentId = targetSegments.some((segment) => segment.segment_id === reuseSegmentId)
    ? reuseSegmentId
    : targetSegments[0]?.segment_id ?? '';
  const refreshSelectedAssets = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
      queryClient.invalidateQueries({queryKey: queryKeys.visualDiscoveryAssets(effectiveStoryId)}),
    ]);
  };
  const reviewMutation = useMutation({
    mutationFn: ({assetId, decision}: {assetId: string; decision: 'approve' | 'reject'}) => {
      if (selectedStory === undefined) throw new Error('当前故事上下文不可用。');
      const body = {
        expected_story_version: selectedStory.version,
        note: decision === 'approve'
          ? 'Approved from the visual asset library after rights and source review.'
          : 'Rejected from the visual asset library after editorial review.',
      };
      return decision === 'approve'
        ? approveVisualDiscoveryAsset(assetId, body)
        : rejectVisualDiscoveryAsset(assetId, body);
    },
    onSuccess: refreshSelectedAssets,
  });
  const reuseMutation = useMutation({
    mutationFn: () => {
      if (
        reuseAssetId === null
        || targetStory?.story_id === undefined
        || targetStory.script === null
        || targetStory.script === undefined
        || effectiveReuseSegmentId === ''
      ) {
        throw new Error('请选择有效的目标故事和脚本段。');
      }
      return reuseApprovedVisualDiscoveryAsset(reuseAssetId, {
        story_id: targetStory.story_id,
        segment_id: effectiveReuseSegmentId,
        expected_story_version: targetStory.version,
        expected_script_revision: targetStory.script.revision,
      });
    },
    onSuccess: async () => {
      if (targetStory?.story_id !== undefined) {
        await Promise.all([
          queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
          queryClient.invalidateQueries({
            queryKey: queryKeys.visualDiscoveryAssets(targetStory.story_id),
          }),
        ]);
        setStoryId(targetStory.story_id);
      }
      setReuseAssetId(null);
      setReuseStoryId('');
      setReuseSegmentId('');
    },
  });
  const error = storiesQuery.error
    ?? storyAssetsQuery.error
    ?? discoveryQuery.error
    ?? sourceMediaQuery.error
    ?? reviewMutation.error
    ?? reuseMutation.error;
  const loading = storiesQuery.isLoading
    || storyAssetsQuery.isLoading
    || discoveryQuery.isLoading
    || sourceMediaQuery.isLoading;

  return (
    <div className="page library-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PRODUCTION LIBRARY</p>
          <h1>画面素材库</h1>
          <p>按故事查看真实素材、来源和权利状态。素材仍由故事脚本拥有，库只负责检索和审计。</p>
        </div>
        {selectedStory?.story_id === undefined ? null : (
          <Link className="button" to={`/stories/${selectedStory.story_id}`}>
            打开故事工作台
          </Link>
        )}
      </div>

      <div className="library-toolbar">
        <label className="field">
          <span>故事</span>
          <select className="select" value={effectiveStoryId} onChange={(event) => setStoryId(event.target.value)}>
            {stories.map((story) => (
              <option key={story.story_id ?? story.trace_id} value={story.story_id}>
                {storyLabel(story)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>素材类型</span>
          <select className="select" value={kind} onChange={(event) => setKind(event.target.value as LibraryKind)}>
            <option value="all">全部素材</option>
            <option value="story">上传与网页截图</option>
            <option value="commons">Commons 审核素材</option>
            <option value="source-video">源视频证据</option>
          </select>
        </label>
        <label className="search-control library-search">
          <Search size={16} aria-hidden="true" />
          <input
            className="input"
            type="search"
            placeholder="搜索文件、作者或许可…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="搜索画面素材"
          />
        </label>
      </div>

      {error === null ? null : <ApiErrorNotice error={error} />}
      {loading ? (
        <div className="asset-library-grid" aria-label="正在加载画面素材">
          {[0, 1, 2].map((item) => <div className="library-asset-card skeleton-card" key={item} />)}
        </div>
      ) : stories.length === 0 ? (
        <div className="empty-state">
          <ImageIcon size={28} aria-hidden="true" />
          <h2>还没有进入脚本阶段的故事</h2>
          <p>素材绑定到不可变的脚本段。先完成初审并生成口播，再添加、搜集和审核画面。</p>
        </div>
      ) : visibleAssets.length === 0 ? (
        <div className="empty-state">
          <Film size={28} aria-hidden="true" />
          <h2>当前故事没有匹配素材</h2>
          <p>素材不会脱离故事上下文单独存在。请打开故事工作台添加画面或采集源视频。</p>
        </div>
      ) : (
        <>
          <div className="library-summary" aria-live="polite">
            <strong>{visibleAssets.length}</strong> 个素材
            <span>{assets.filter((asset) => asset.status === 'approved').length} 个可用于制作</span>
            <span>{assets.filter((asset) => asset.status === 'review').length} 个待权利审核</span>
          </div>
          <div className="asset-library-grid">
            {visibleAssets.map((asset) => (
              <AssetPreview
                asset={asset}
                busy={reviewMutation.isPending || reuseMutation.isPending}
                key={`${asset.kind}-${asset.id}`}
                onApprove={() => reviewMutation.mutate({assetId: asset.id, decision: 'approve'})}
                onReject={() => reviewMutation.mutate({assetId: asset.id, decision: 'reject'})}
                onReuse={() => setReuseAssetId(asset.id)}
              />
            ))}
          </div>
        </>
      )}
      {reuseAssetId === null ? null : (
        <ModalDialog
          open
          className="create-drawer"
          labelledBy="reuse-visual-heading"
          onClose={() => setReuseAssetId(null)}
        >
          <div className="panel-header">
            <div>
              <p className="eyebrow">REUSE VERIFIED ASSET</p>
              <h2 id="reuse-visual-heading">复用已批准素材</h2>
            </div>
            <button className="icon-button" type="button" aria-label="关闭" onClick={() => setReuseAssetId(null)}>
              ×
            </button>
          </div>
          <form
            className="panel-body form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              reuseMutation.mutate();
            }}
          >
            <p className="field-hint wide">
              已校验字节会被复用，但目标故事仍会得到新的 staged 记录并再次人工审核。
            </p>
            <label className="field wide">
              <span>目标故事</span>
              <select
                className="select"
                required
                value={targetStory?.story_id ?? ''}
                onChange={(event) => {
                  setReuseStoryId(event.target.value);
                  setReuseSegmentId('');
                }}
              >
                {stories.filter((story) => story.story_id !== effectiveStoryId).map((story) => (
                  <option key={story.story_id} value={story.story_id}>{storyLabel(story)}</option>
                ))}
              </select>
            </label>
            <label className="field wide">
              <span>目标脚本段</span>
              <select
                className="select"
                required
                value={effectiveReuseSegmentId}
                onChange={(event) => setReuseSegmentId(event.target.value)}
              >
                {targetSegments.map((segment, index) => (
                  <option key={segment.segment_id} value={segment.segment_id}>
                    第 {index + 1} 段 · {segment.spoken_text.slice(0, 46)}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-actions wide">
              <button className="button" type="button" onClick={() => setReuseAssetId(null)}>取消</button>
              <button
                className="button primary"
                type="submit"
                disabled={reuseMutation.isPending || targetStory === undefined || effectiveReuseSegmentId === ''}
              >
                {reuseMutation.isPending ? '正在复用…' : '创建待审复用记录'}
              </button>
            </div>
          </form>
        </ModalDialog>
      )}
    </div>
  );
}
