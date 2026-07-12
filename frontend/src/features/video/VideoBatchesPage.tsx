import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Clapperboard, Eye, Plus, Trash2} from 'lucide-react';
import {useState} from 'react';

import {createVideoBatch, listVideoBatches} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/Toast';

const STATUS_LABELS: Record<string, string> = {
  PENDING_TIMELINE_REVIEW: '等待时间轴审阅',
  READY_TO_RENDER: '待渲染',
  RENDERING: '渲染中',
  RENDERED: '已完成',
  REJECTED: '已驳回',
  FAILED: '失败',
};

function statusTone(status: string): string {
  if (status === 'RENDERED') return 'success';
  if (status === 'FAILED' || status === 'REJECTED') return 'danger';
  if (status === 'RENDERING') return 'info';
  return 'caution';
}

export function VideoBatchesPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({storyCount: 5, style: '温暖播报'});
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.videoBatches(),
    queryFn: listVideoBatches,
  });
  const createMutation = useMutation({
    mutationFn: createVideoBatch,
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.videoBatches()});
      setShowCreate(false);
      pushToast({message: '视频批次已创建，进入时间轴审阅阶段。', durationMs: 3000});
    },
  });

  return (
    <div className="page video-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">VIDEO PRODUCTION</p>
          <h1>视频批次</h1>
          <p>编排视频批次的完整生命周期——从故事选择、时间轴审阅到渲染输出。</p>
        </div>
        <button className="button primary" type="button" onClick={() => setShowCreate(true)} disabled={showCreate}>
          <Plus size={18} aria-hidden="true" /> 新建批次
        </button>
      </div>

      {query.isLoading ? (
        <div className="loading-state">正在加载视频批次…</div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data !== undefined && (query.data as unknown[]).length === 0 ? (
        <EmptyState title="尚无视频批次" description="点击「新建批次」选择已审过的故事编排一期视频。" action={{label: '新建批次', onClick: () => setShowCreate(true)}} />
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>批次 ID</th>
                <th>状态</th>
                <th>版本</th>
                <th>创建时间</th>
                <th className="actions-cell">操作</th>
              </tr>
            </thead>
            <tbody>
              {(query.data as unknown[])?.map((batch: any) => {
                const status = String(batch['status'] ?? '');
                return (
                  <tr key={String(batch['batch_id'])}>
                    <td className="metadata">{String(batch['batch_id'] ?? '').slice(0, 8)}…</td>
                    <td><span className={`badge ${statusTone(status)}`}>{STATUS_LABELS[status] ?? status}</span></td>
                    <td>v{String(batch['version'] ?? 1)}</td>
                    <td className="metadata">{String(batch['created_at'] ?? '—')}</td>
                    <td className="actions-cell">
                      <button className="icon-button" type="button" aria-label="查看详情" onClick={() => setSelectedId(String(batch['batch_id']))}>
                        <Eye size={16} aria-hidden="true" />
                      </button>
                      <button className="icon-button danger" type="button" aria-label="删除批次" onClick={() => setDeleteTarget(String(batch['batch_id']))}>
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Batch detail panel */}
      {selectedId !== null ? (
        <dialog className="create-drawer" open onCancel={(e) => { e.preventDefault(); setSelectedId(null); }}>
          <div className="panel-header">
            <div>
              <p className="eyebrow">BATCH DETAIL</p>
              <h2>批次详情</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setSelectedId(null)} aria-label="关闭">✕</button>
          </div>
          <div className="panel-body">
            <p className="eyebrow">Batch {selectedId.slice(0, 8)}…</p>
            <div className="info-grid">
              <div className="info-item"><span className="label">状态</span><span className="value">—</span></div>
              <div className="info-item"><span className="label">版本</span><span className="value">—</span></div>
              <div className="info-item"><span className="label">故事数</span><span className="value">—</span></div>
              <div className="info-item"><span className="label">总时长</span><span className="value">—</span></div>
            </div>
            <div style={{marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
              <button className="button" type="button" onClick={() => pushToast({message: '时间轴审阅功能待后端实现。', variant: 'caution', durationMs: 3000})}>
                <Clapperboard size={16} aria-hidden="true" /> 审阅时间轴 (待后端)
              </button>
              <button className="button primary" type="button" onClick={() => pushToast({message: '渲染功能待后端实现 Remotion 桥接。', variant: 'caution', durationMs: 3000})}>
                开始渲染 (待后端)
              </button>
              <button className="button danger" type="button" onClick={() => pushToast({message: '取消渲染需后端实现 cancel 路由。', variant: 'caution', durationMs: 3000})}>
                取消渲染 (待后端)
              </button>
            </div>
            <div style={{marginTop: 16}}>
              <h3>时间轴 (JSON)</h3>
              <div className="code-block">{`{
  "timeline": [
    { "segment_id": "…", "start_ms": 0, "end_ms": 5000, "text": "…" }
  ],
  "total_duration_ms": 0
}`}</div>
            </div>
          </div>
        </dialog>
      ) : null}

      {/* Create form */}
      {showCreate ? (
        <dialog className="create-drawer" open onCancel={(e) => { e.preventDefault(); setShowCreate(false); }}>
          <div className="panel-header">
            <div>
              <p className="eyebrow">NEW BATCH</p>
              <h2>新建视频批次</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setShowCreate(false)} aria-label="关闭">✕</button>
          </div>
          <form className="panel-body form-grid" onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate({story_count: createForm.storyCount, style: createForm.style});
          }}>
            <label className="field">
              <span>选取故事数</span>
              <input className="input" type="number" min={1} max={20} value={createForm.storyCount} onChange={(e) => setCreateForm({...createForm, storyCount: Number(e.target.value)})} />
            </label>
            <label className="field">
              <span>风格</span>
              <input className="input" value={createForm.style} onChange={(e) => setCreateForm({...createForm, style: e.target.value})} />
            </label>
            {createMutation.error !== null && <div className="wide"><ApiErrorNotice error={createMutation.error} /></div>}
            <div className="form-actions wide">
              <button className="button" type="button" onClick={() => setShowCreate(false)}>取消</button>
              <button className="button primary" type="submit" disabled={createMutation.isPending}>创建批次</button>
            </div>
          </form>
        </dialog>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除视频批次"
        message="删除批次后，关联的故事占用将被释放。此操作需后端 DELETE 路由（当前未实现）。"
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={() => { if (deleteTarget !== null) pushToast({message: '删除批次需后端实现 DELETE 路由。', variant: 'caution', durationMs: 3000}); setDeleteTarget(null); }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
