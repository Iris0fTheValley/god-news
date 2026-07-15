import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Download, ExternalLink, Film, ShieldAlert, ShieldCheck} from 'lucide-react';

import {
  acquireSourceMedia,
  listSourceMediaArtifacts,
  sourceMediaContentUrl,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {SourceMediaArtifact, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {useToast} from '../../components/toastContext';

interface SourceMediaPanelProps {
  story: Story;
}

function formatBytes(sizeBytes: number): string {
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function sourceHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return '来源链接';
  }
}

function RightsBadge({artifact}: {artifact: SourceMediaArtifact}) {
  return artifact.publish_eligible ? (
    <span className="badge success"><ShieldCheck size={13} aria-hidden="true" /> 可进入发布流程</span>
  ) : (
    <span className="badge caution"><ShieldAlert size={13} aria-hidden="true" /> 仅供审核，权利待确认</span>
  );
}

export function SourceMediaPanel({story}: SourceMediaPanelProps) {
  const storyId = story.story_id ?? '';
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const videos = (story.provenance?.media ?? []).flatMap((media, mediaIndex) => (
    media.kind === 'video' ? [{media, mediaIndex}] : []
  ));
  const mediaQuery = useQuery({
    queryKey: queryKeys.sourceMedia(storyId),
    queryFn: () => listSourceMediaArtifacts(storyId),
    enabled: storyId !== '' && videos.length > 0,
  });
  const acquireMutation = useMutation({
    mutationFn: (mediaIndex: number) => acquireSourceMedia(storyId, {
      expected_story_version: story.version,
      media_index: mediaIndex,
      requested_by: 'story-workbench',
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.sourceMedia(storyId)});
      pushToast({message: '源视频已下载并生成不可变证据快照。', durationMs: 3000});
    },
    onError: (error) => {
      pushToast({
        message: `源视频采集失败：${error instanceof Error ? error.message : '未知错误'}`,
        variant: 'caution',
        durationMs: 5000,
      });
    },
  });
  if (videos.length === 0) return null;
  const artifactsByIndex = new Map(
    (mediaQuery.data ?? []).map((artifact) => [artifact.media_index, artifact]),
  );

  return (
    <section className="panel source-media-panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">SOURCE VIDEO EVIDENCE</p>
          <h2>源视频与权利证据</h2>
        </div>
        <span className="metadata"><Film size={15} aria-hidden="true" /> {videos.length} 个候选</span>
      </div>
      <div className="panel-body source-media-list">
        {mediaQuery.error === null ? null : (
          <ApiErrorNotice error={mediaQuery.error} onRetry={() => void mediaQuery.refetch()} />
        )}
        {videos.map(({media, mediaIndex}) => {
          const artifact = artifactsByIndex.get(mediaIndex);
          const isAcquiring = acquireMutation.isPending
            && acquireMutation.variables === mediaIndex;
          return (
            <article className="source-media-card" key={`${mediaIndex}-${media.url}`}>
              <div className="source-media-heading">
                <div>
                  <h3>视频候选 {String(mediaIndex + 1).padStart(2, '0')}</h3>
                  <p className="metadata">
                    {sourceHost(media.url)}
                    {media.duration_ms === null || media.duration_ms === undefined
                      ? ''
                      : ` · ${(media.duration_ms / 1000).toFixed(1)}s（来源标注）`}
                  </p>
                </div>
                <a className="button secondary" href={media.url} target="_blank" rel="noreferrer">
                  查看来源 <ExternalLink size={14} aria-hidden="true" />
                </a>
              </div>
              {artifact === undefined ? (
                <div className="source-media-pending">
                  <p>
                    下载只用于编辑审核；系统不会把公开可访问误判为可重新发布。
                  </p>
                  <button
                    className="button"
                    type="button"
                    disabled={acquireMutation.isPending || mediaQuery.isLoading}
                    onClick={() => acquireMutation.mutate(mediaIndex)}
                  >
                    <Download size={15} aria-hidden="true" />
                    {isAcquiring ? '正在采集并校验…' : '采集供审核'}
                  </button>
                </div>
              ) : (
                <div className="source-media-artifact">
                  <video controls preload="metadata" src={sourceMediaContentUrl(storyId, artifact.artifact_id ?? '')}>
                    浏览器不支持视频播放。
                  </video>
                  <div className="source-media-evidence">
                    <RightsBadge artifact={artifact} />
                    <p>{artifact.attribution.attribution_text}</p>
                    <p className="metadata">
                      {artifact.probe.width}×{artifact.probe.height} · {(artifact.probe.duration_ms / 1000).toFixed(1)}s · {artifact.probe.video_codec}
                      {artifact.probe.audio_codec === null || artifact.probe.audio_codec === undefined ? ' · 无音轨' : ` / ${artifact.probe.audio_codec}`}
                    </p>
                    <p className="metadata">
                      {formatBytes(artifact.size_bytes)} · SHA-256 {artifact.sha256.slice(0, 12)}… · 权利状态 {artifact.rights.status} · 采集人 {artifact.acquired_by}
                    </p>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
