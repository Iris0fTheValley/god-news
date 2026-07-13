import {useQuery} from '@tanstack/react-query';
import {Music} from 'lucide-react';

import {listBgmTracks} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {EmptyState} from '../../components/EmptyState';

function formatBytes(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${String(sizeBytes)} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function BgmPage() {
  const query = useQuery({
    queryKey: queryKeys.bgmTracks(),
    queryFn: listBgmTracks,
  });

  return (
    <div className="page bgm-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">BACKGROUND MUSIC</p>
          <h1>BGM 管理</h1>
          <p>扫描可用于视频批次的本地 BGM 目录。选择、音量和循环设置属于视频批次创建契约。</p>
        </div>
      </div>

      {query.isLoading ? (
        <div className="loading-state">正在扫描 BGM 文件夹…</div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data !== undefined && query.data.length === 0 ? (
        <EmptyState
          title="BGM 文件夹为空"
          description="将 .mp3 / .wav / .flac / .ogg 文件放入配置的 BGM 目录后刷新。"
          icon={<Music size={40} strokeWidth={1.5} aria-hidden="true" />}
        />
      ) : (
        <div className="bgm-grid">
          {query.data?.map((track) => (
            <article key={track.track_id} className="bgm-card">
              <div>
                <h4>{track.display_name}</h4>
                <p className="metadata">{track.relative_path}</p>
                <span className="metadata">{formatBytes(track.size_bytes)}</span>
              </div>
              <code className="metadata">{track.track_id.slice(0, 12)}…</code>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
