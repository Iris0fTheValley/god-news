import {useQuery} from '@tanstack/react-query';
import {Music, Play, Volume2} from 'lucide-react';
import {useState} from 'react';

import {listBgmTracks} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/Toast';

export function BgmPage() {
  const {push: pushToast} = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [volume, setVolume] = useState(0.4);
  const [loop, setLoop] = useState(true);

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
          <p>从本地 BGM 文件夹中选择背景音乐。支持试听、音量调节和循环播放设置。</p>
        </div>
        {selectedId !== null ? (
          <div style={{display: 'flex', gap: 12, alignItems: 'center'}}>
            <label className="inline-field">
              <Volume2 size={15} aria-hidden="true" />
              <input type="number" min={0} max={1} step={0.05} value={volume} onChange={(e) => setVolume(Number(e.target.value))} style={{width: 62}} />
            </label>
            <label className="checkbox-field">
              <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />
              <span>循环</span>
            </label>
            <button
              className="button primary"
              type="button"
              onClick={() => pushToast({message: `已选择 BGM (音量 ${volume.toFixed(2)}，循环: ${loop ? '是' : '否'})——实际应用需在视频批次中选择。`, durationMs: 3000})}
            >
              确认选择
            </button>
          </div>
        ) : null}
      </div>

      {query.isLoading ? (
        <div className="loading-state">正在扫描 BGM 文件夹…</div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data !== undefined && (query.data as unknown[]).length === 0 ? (
        <EmptyState
          title="BGM 文件夹为空"
          description="将 .mp3 / .wav / .flac / .ogg 文件放入配置的 BGM 目录后刷新。"
          icon={<Music size={40} strokeWidth={1.5} aria-hidden="true" />}
        />
      ) : (
        <div className="bgm-grid">
          {(query.data as unknown[])?.map((track: any) => {
            const tid = String(track['track_id'] ?? '');
            return (
              <div key={tid} className={`bgm-card ${selectedId === tid ? 'selected' : ''}`}>
                <div>
                  <h4>{String(track['display_name'] ?? tid)}</h4>
                  <span className="metadata">
                    {String(track['format'] ?? '').toUpperCase()}
                    {track['duration_seconds'] != null ? ` · ${String(track['duration_seconds'])}s` : ''}
                  </span>
                  {track['local_path'] != null ? (
                    <audio controls preload="metadata" style={{width: '100%', marginTop: 6}}>
                      <source src={`/api/v1/video/bgm/stream?path=${encodeURIComponent(String(track['local_path']))}`} />
                    </audio>
                  ) : null}
                </div>
                <button
                  className={`button ${selectedId === tid ? 'primary' : ''} small`}
                  type="button"
                  onClick={() => selectedId === tid ? setSelectedId(null) : setSelectedId(tid)}
                >
                  <Play size={14} aria-hidden="true" />
                  {selectedId === tid ? '已选' : '选择'}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
