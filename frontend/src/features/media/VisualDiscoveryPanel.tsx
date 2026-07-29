import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Check, ExternalLink, Film, Search, ShieldCheck, X} from 'lucide-react';
import {useState, type FormEvent} from 'react';

import {
  approveVisualDiscoveryAsset,
  listStoryVisualDiscoveryAssets,
  rejectVisualDiscoveryAsset,
  searchCommonsVisuals,
  stageCommonsVisual,
  visualDiscoveryAssetContentUrl,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {CommonsVisualCandidate, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

interface VisualDiscoveryPanelProps {
  story: Story;
}

export function VisualDiscoveryPanel({story}: VisualDiscoveryPanelProps) {
  const queryClient = useQueryClient();
  const segments = story.script?.segments ?? [];
  const storyId = story.story_id ?? '';
  const storyVersion = story.version ?? 0;
  const [query, setQuery] = useState('');
  const [segmentId, setSegmentId] = useState(segments[0]?.segment_id ?? '');
  const [candidates, setCandidates] = useState<CommonsVisualCandidate[]>([]);
  const effectiveSegmentId = segments.some((segment) => segment.segment_id === segmentId)
    ? segmentId
    : segments[0]?.segment_id ?? '';

  const assetsQuery = useQuery({
    queryKey: queryKeys.visualDiscoveryAssets(storyId),
    queryFn: () => listStoryVisualDiscoveryAssets(storyId),
    enabled: storyId !== '' && story.script !== null && story.script !== undefined,
  });
  const refreshAssets = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.visualDiscoveryAssets(storyId),
    });
  };
  const searchMutation = useMutation({
    mutationFn: (term: string) => searchCommonsVisuals(term),
    onSuccess: (result) => setCandidates(result.candidates ?? []),
  });
  const stageMutation = useMutation({
    mutationFn: (candidate: CommonsVisualCandidate) => {
      if (story.script === null || story.script === undefined || effectiveSegmentId === '') {
        throw new Error('请先选择一个当前脚本段落。');
      }
      return stageCommonsVisual({
        file_title: candidate.file_title,
        story_id: storyId,
        segment_id: effectiveSegmentId,
        expected_story_version: storyVersion,
        expected_script_revision: story.script.revision,
      });
    },
    onSuccess: refreshAssets,
  });
  const approveMutation = useMutation({
    mutationFn: (assetId: string) => approveVisualDiscoveryAsset(assetId, {
      expected_story_version: storyVersion,
      note: 'Operator approved after reviewing provider-derived rights and media evidence.',
    }),
    onSuccess: refreshAssets,
  });
  const rejectMutation = useMutation({
    mutationFn: (assetId: string) => rejectVisualDiscoveryAsset(assetId, {
      expected_story_version: storyVersion,
      note: 'Operator rejected this visual candidate.',
    }),
    onSuccess: refreshAssets,
  });
  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const term = query.trim();
    if (term !== '') searchMutation.mutate(term);
  };
  const error = assetsQuery.error
    ?? searchMutation.error
    ?? stageMutation.error
    ?? approveMutation.error
    ?? rejectMutation.error;

  if (story.script === null || story.script === undefined) return null;

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">VISUAL DISCOVERY</p>
          <h2>可授权画面素材</h2>
        </div>
        <span className="metadata">
          <ShieldCheck size={15} aria-hidden="true" /> Wikimedia Commons
        </span>
      </div>
      <div className="panel-body visual-discovery-panel">
        <p className="field-hint">
          搜索结果只展示官方 API 返回的来源、作者和许可。素材必须先下载校验，再由操作员批准，才能进入 B-roll。
        </p>
        {error === null ? null : <ApiErrorNotice error={error} />}
        <form className="visual-discovery-search" onSubmit={submitSearch}>
          <label className="field">
            <span>搜索 Commons</span>
            <input
              className="input"
              value={query}
              placeholder="例如：NASA moon transit"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label className="field">
            <span>绑定脚本段落</span>
            <select
              className="select"
              value={effectiveSegmentId}
              onChange={(event) => setSegmentId(event.target.value)}
            >
              {segments.map((segment, index) => (
                <option key={segment.segment_id} value={segment.segment_id}>
                  第 {String(index + 1)} 段 · {segment.spoken_text.slice(0, 30)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button"
            type="submit"
            disabled={searchMutation.isPending || query.trim() === ''}
          >
            <Search size={16} aria-hidden="true" />
            {searchMutation.isPending ? '正在搜索' : '搜索素材'}
          </button>
        </form>

        {candidates.length === 0 ? null : (
          <div className="visual-discovery-grid" aria-label="Commons 搜索结果">
            {candidates.map((candidate) => (
              <article className="visual-candidate" key={candidate.page_id}>
                <div className="visual-candidate-heading">
                  <Film size={18} aria-hidden="true" />
                  <strong>{candidate.file_title.replace(/^File:/, '')}</strong>
                </div>
                <p className="metadata">
                  {candidate.kind.toUpperCase()} · {candidate.width}×{candidate.height}
                  {candidate.duration_ms === null || candidate.duration_ms === undefined
                    ? ''
                    : ` · ${(candidate.duration_ms / 1000).toFixed(1)}s`}
                </p>
                <p>{candidate.attribution.attribution_text}</p>
                <p className="metadata">
                  许可：{candidate.rights.source_license_label ?? candidate.rights.license}
                  {candidate.rights.requires_attribution ? ' · 需要署名' : ' · 无强制署名'}
                </p>
                <div className="inline-actions">
                  <a
                    className="button ghost"
                    href={candidate.canonical_page_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    核对来源 <ExternalLink size={14} aria-hidden="true" />
                  </a>
                  <button
                    className="button secondary"
                    type="button"
                    disabled={!candidate.rights.allows_commercial_use
                      || !candidate.rights.allows_derivatives
                      || candidate.rights.requires_human_review
                      || stageMutation.isPending
                      || effectiveSegmentId === ''}
                    onClick={() => stageMutation.mutate(candidate)}
                  >
                    下载并校验
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        {(assetsQuery.data ?? []).length === 0 ? null : (
          <div className="visual-discovery-assets">
            <h3>已暂存素材</h3>
            {(assetsQuery.data ?? []).map((asset) => (
              <article className="visual-candidate" key={asset.asset_id}>
                <div className="visual-candidate-heading">
                  <span className={`badge ${asset.status === 'approved' ? 'success' : 'info'}`}>
                    {asset.status}
                  </span>
                  <strong>{asset.candidate.file_title.replace(/^File:/, '')}</strong>
                </div>
                <p className="metadata">
                  SHA-256 {asset.sha256?.slice(0, 16) ?? '尚未校验'}…
                  {asset.probed_duration_ms === null || asset.probed_duration_ms === undefined
                    ? ''
                    : ` · ffprobe ${(asset.probed_duration_ms / 1000).toFixed(1)}s`}
                </p>
                <p>{asset.candidate.attribution.attribution_text}</p>
                <div className="inline-actions">
                  {asset.status === 'approved' ? (
                    <a
                      className="button ghost"
                      href={visualDiscoveryAssetContentUrl(asset.asset_id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      预览已批准媒体 <ExternalLink size={14} aria-hidden="true" />
                    </a>
                  ) : asset.status === 'staged' ? (
                    <>
                      <button
                        className="button"
                        type="button"
                        disabled={approveMutation.isPending}
                        onClick={() => approveMutation.mutate(asset.asset_id)}
                      >
                        <Check size={15} aria-hidden="true" /> 批准进入 B-roll
                      </button>
                      <button
                        className="button ghost danger"
                        type="button"
                        disabled={rejectMutation.isPending}
                        onClick={() => rejectMutation.mutate(asset.asset_id)}
                      >
                        <X size={15} aria-hidden="true" /> 拒绝
                      </button>
                    </>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
