import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Clapperboard, Eye, Film, Plus, RefreshCw, Square, Trash2} from 'lucide-react';
import {useState} from 'react';

import {
  cancelVideoRender,
  createVideoBatch,
  deleteVideoBatch,
  getVideoBatch,
  listBgmTracks,
  listVideoBatches,
  renderVideoBatch,
  submitTimelineReview,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {CreateVideoBatch, VideoBatch, VideoBatchStatus} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/toastContext';

const STATUS_LABELS: Record<VideoBatchStatus, string> = {
  PENDING_TIMELINE_REVIEW: '等待时间轴审阅',
  READY_TO_RENDER: '待渲染',
  RENDERING: '渲染中',
  RENDERED: '已完成',
  REJECTED: '已驳回',
  CANCELLED: '已取消',
  FAILED: '失败',
};

function statusTone(status: VideoBatchStatus): string {
  if (status === 'RENDERED') return 'success';
  if (status === 'FAILED' || status === 'REJECTED') return 'danger';
  if (status === 'CANCELLED') return 'muted';
  if (status === 'RENDERING') return 'info';
  return 'caution';
}

function newBatchForm(): CreateVideoBatch {
  return {
    title: '',
    subtitle: null,
    story_ids: [],
    max_stories: 5,
    bgm_track_id: null,
    bgm_volume: 0.12,
    bgm_loop: true,
  };
}

function batchCanBeCancelled(status: VideoBatchStatus): boolean {
  return status === 'PENDING_TIMELINE_REVIEW' || status === 'READY_TO_RENDER' || status === 'FAILED';
}

function BatchDetail({batch, onDelete, onCancel, onApprove, onRender}: {
  batch: VideoBatch;
  onDelete: (batchId: string) => void;
  onCancel: (batchId: string) => void;
  onApprove: (batch: VideoBatch) => void;
  onRender: (batch: VideoBatch) => void;
}) {
  const batchId = batch.batch_id;
  const totalDuration = batch.remotion_props.manifest.total_duration_ms;
  const canApprove = batch.status === 'PENDING_TIMELINE_REVIEW';
  const canRender = batch.status === 'READY_TO_RENDER' || batch.status === 'FAILED';

  return (
    <>
      <div className="info-grid">
        <div className="info-item"><span className="label">状态</span><span className={`badge ${statusTone(batch.status)}`}>{STATUS_LABELS[batch.status]}</span></div>
        <div className="info-item"><span className="label">版本</span><span className="value">v{String(batch.version)}</span></div>
        <div className="info-item"><span className="label">故事数</span><span className="value">{String(batch.stories.length)}</span></div>
        <div className="info-item"><span className="label">总时长</span><span className="value">{(totalDuration / 1000).toFixed(1)}s</span></div>
      </div>
      {batch.last_failure === undefined || batch.last_failure === null ? null : (
        <div className="error-banner" style={{marginTop: 16}}><strong>上次渲染失败：</strong>{batch.last_failure.message}</div>
      )}
      <div style={{marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        {batchId === undefined || !canApprove ? null : <button className="button" type="button" onClick={() => onApprove(batch)}><Clapperboard size={16} aria-hidden="true" /> 批准时间轴</button>}
        {batchId === undefined || !canRender ? null : <button className="button primary" type="button" onClick={() => onRender(batch)}><Film size={16} aria-hidden="true" /> 开始渲染</button>}
        {batchId === undefined || !batchCanBeCancelled(batch.status) ? null : <button className="button danger" type="button" onClick={() => onCancel(batchId)}><Square size={15} aria-hidden="true" /> 取消批次</button>}
        {batchId === undefined || batch.status === 'RENDERING' || batch.status === 'RENDERED' ? null : <button className="button danger" type="button" onClick={() => onDelete(batchId)}><Trash2 size={15} aria-hidden="true" /> 删除批次</button>}
      </div>
      <section style={{marginTop: 16}}>
        <h3>时间轴</h3>
        <div className="table-container" style={{maxHeight: 300, overflowY: 'auto'}}>
          <table className="table dense">
            <thead><tr><th>故事</th><th>时间段</th><th>片段数</th></tr></thead>
            <tbody>{batch.stories.map((story) => <tr key={story.story_id}><td>{story.title}</td><td className="metadata">{(story.chapter_start_ms / 1000).toFixed(1)} → {(story.chapter_end_ms / 1000).toFixed(1)}s</td><td className="metadata">{String(story.manifest.timeline.length)}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function VideoBatchesPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateVideoBatch>(newBatchForm);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const query = useQuery({queryKey: queryKeys.videoBatches(), queryFn: () => listVideoBatches(), refetchInterval: 10_000});
  const bgmQuery = useQuery({queryKey: queryKeys.bgmTracks(), queryFn: listBgmTracks});
  const detailQuery = useQuery({
    queryKey: queryKeys.videoBatch(selectedId ?? ''),
    queryFn: () => getVideoBatch(selectedId ?? ''),
    enabled: selectedId !== null,
    refetchInterval: (state) => state.state.data?.status === 'RENDERING' ? 5_000 : false,
  });
  const refreshBatches = () => void queryClient.invalidateQueries({queryKey: queryKeys.videoBatches()});
  const refreshSelected = (batch: VideoBatch) => {
    if (batch.batch_id !== undefined) void queryClient.invalidateQueries({queryKey: queryKeys.videoBatch(batch.batch_id)});
  };
  const createMutation = useMutation({
    mutationFn: createVideoBatch,
    onSuccess: (batch) => {
      refreshBatches();
      setShowCreate(false);
      setCreateForm(newBatchForm());
      if (batch.batch_id !== undefined) setSelectedId(batch.batch_id);
      pushToast({message: '视频批次已创建，等待人工审阅时间轴。', durationMs: 3000});
    },
  });
  const approveMutation = useMutation({
    mutationFn: (batch: VideoBatch) => {
      if (batch.batch_id === undefined) throw new Error('批次缺少标识。');
      return submitTimelineReview(batch.batch_id, {
        expected_batch_version: batch.version,
        decision: 'approve',
        reviewer_id: 'web-operator',
        story_order: batch.stories.map((story) => story.story_id),
      });
    },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '时间轴已批准。', durationMs: 3000}); },
  });
  const renderMutation = useMutation({
    mutationFn: (batch: VideoBatch) => {
      if (batch.batch_id === undefined) throw new Error('批次缺少标识。');
      return renderVideoBatch(batch.batch_id, {expected_batch_version: batch.version});
    },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '渲染请求已提交。', durationMs: 3000}); },
  });
  const cancelMutation = useMutation({
    mutationFn: cancelVideoRender,
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '批次已取消，故事占用已释放。', variant: 'caution', durationMs: 3000}); },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteVideoBatch,
    onSuccess: () => { refreshBatches(); setDeleteTarget(null); setSelectedId(null); pushToast({message: '批次已删除，故事占用已释放。', variant: 'caution', durationMs: 3000}); },
  });
  const mutationError = createMutation.error ?? approveMutation.error ?? renderMutation.error ?? cancelMutation.error ?? deleteMutation.error;
  const batches = query.data ?? [];

  return (
    <div className="page video-page">
      <div className="page-heading">
        <div><p className="eyebrow">VIDEO PRODUCTION</p><h1>视频批次</h1><p>批次绑定经终审的故事、已审阅的输入资产快照和显式时间轴审批。</p></div>
        <button className="button primary" type="button" onClick={() => setShowCreate(true)} disabled={showCreate}><Plus size={18} aria-hidden="true" /> 新建批次</button>
      </div>

      {query.isLoading ? <div className="loading-state">正在加载视频批次…</div>
        : query.error !== null ? <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
          : batches.length === 0 ? <EmptyState title="尚无视频批次" description="创建批次会自动从未占用的 DONE 故事中选择候选项。" action={{label: '新建批次', onClick: () => setShowCreate(true)}} />
            : <div className="table-container"><table className="table"><thead><tr><th>标题</th><th>状态</th><th>版本</th><th>创建时间</th><th className="actions-cell">操作</th></tr></thead><tbody>
              {batches.map((batch) => {
                const batchId = batch.batch_id;
                return <tr key={batchId ?? `${batch.title}-${batch.created_at ?? batch.version}`}><td><strong>{batch.title}</strong></td><td><span className={`badge ${statusTone(batch.status)}`}>{batch.status === 'RENDERING' ? <RefreshCw className="spinning" size={12} aria-hidden="true" /> : null} {STATUS_LABELS[batch.status]}</span></td><td>v{String(batch.version)}</td><td className="metadata">{batch.created_at ?? '—'}</td><td className="actions-cell">{batchId === undefined ? null : <button className="icon-button" type="button" aria-label="查看详情" onClick={() => setSelectedId(batchId)}><Eye size={16} aria-hidden="true" /></button>}</td></tr>;
              })}
            </tbody></table></div>}

      {selectedId === null ? null : <dialog className="create-drawer wide-drawer" open onCancel={(event) => { event.preventDefault(); setSelectedId(null); }}><div className="panel-header"><div><p className="eyebrow">BATCH DETAIL</p><h2>批次详情</h2></div><button className="icon-button" type="button" onClick={() => setSelectedId(null)} aria-label="关闭">✕</button></div><div className="panel-body">{detailQuery.isLoading ? <div className="loading-state">正在加载批次详情…</div> : detailQuery.error !== null ? <ApiErrorNotice error={detailQuery.error} onRetry={() => void detailQuery.refetch()} /> : detailQuery.data === undefined ? null : <BatchDetail batch={detailQuery.data} onDelete={setDeleteTarget} onCancel={(batchId) => cancelMutation.mutate(batchId)} onApprove={(batch) => approveMutation.mutate(batch)} onRender={(batch) => renderMutation.mutate(batch)} />}{mutationError === null ? null : <ApiErrorNotice error={mutationError} />}</div></dialog>}

      {showCreate ? <dialog className="create-drawer" open onCancel={(event) => { event.preventDefault(); setShowCreate(false); }}><div className="panel-header"><div><p className="eyebrow">NEW BATCH</p><h2>新建视频批次</h2></div><button className="icon-button" type="button" onClick={() => setShowCreate(false)} aria-label="关闭">✕</button></div><form className="panel-body form-grid" onSubmit={(event) => { event.preventDefault(); createMutation.mutate(createForm); }}><label className="field wide"><span>标题</span><input className="input" required value={createForm.title} onChange={(event) => setCreateForm({...createForm, title: event.target.value})} /></label><label className="field wide"><span>副标题（可选）</span><input className="input" value={createForm.subtitle ?? ''} onChange={(event) => setCreateForm({...createForm, subtitle: event.target.value === '' ? null : event.target.value})} /></label><label className="field"><span>自动选择故事数</span><input className="input" type="number" min={1} max={15} value={createForm.max_stories} onChange={(event) => setCreateForm({...createForm, max_stories: Number(event.target.value)})} /></label><label className="field"><span>BGM（可选）</span><select className="select" value={createForm.bgm_track_id ?? ''} onChange={(event) => setCreateForm({...createForm, bgm_track_id: event.target.value === '' ? null : event.target.value})}><option value="">不使用 BGM</option>{bgmQuery.data?.map((track) => <option key={track.track_id} value={track.track_id}>{track.display_name}</option>)}</select></label><label className="field"><span>BGM 音量</span><input className="input" type="number" min={0} max={1} step={0.01} value={createForm.bgm_volume} onChange={(event) => setCreateForm({...createForm, bgm_volume: Number(event.target.value)})} /></label><label className="checkbox-field"><input type="checkbox" checked={createForm.bgm_loop} onChange={(event) => setCreateForm({...createForm, bgm_loop: event.target.checked})} /><span>BGM 循环</span></label>{createMutation.error === null ? null : <div className="wide"><ApiErrorNotice error={createMutation.error} /></div>}<div className="form-actions wide"><button className="button" type="button" onClick={() => setShowCreate(false)}>取消</button><button className="button primary" type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? '创建中…' : '创建并审阅'}</button></div></form></dialog> : null}

      <ConfirmDialog open={deleteTarget !== null} title="删除视频批次" message="未渲染批次会被删除并释放故事占用；已渲染的批次是不可删除的审计证据。" variant="danger" confirmLabel="确认删除" onConfirm={() => { if (deleteTarget !== null) deleteMutation.mutate(deleteTarget); }} onCancel={() => setDeleteTarget(null)} />
    </div>
  );
}
