import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, Clapperboard, Eye, Film, Headphones, Mic2, Plus, RefreshCw, Square, Trash2, XCircle} from 'lucide-react';
import {useState} from 'react';

import {
  cancelVideoRender,
  createVideoBatch,
  deleteVideoBatch,
  getVideoBatch,
  listBgmTracks,
  listRoles,
  listVideoBatches,
  renderVideoBatch,
  submitTimelineReview,
  submitVideoBatchNarrationReview,
  synthesizeVideoBatchNarration,
  videoBatchAudioClipUrl,
  videoBatchOutputUrl,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {
  CreateVideoBatch,
  NarrationReviewDecision,
  RoleProfile,
  ScriptDocument,
  SubmitTimelineReview,
  VideoBatch,
  VideoBatchStatus,
} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/toastContext';
import {ScriptEditor} from '../script/ScriptEditor';
import {canEditNarration, canPreviewBatchNarration} from './narrationReviewState';

const STATUS_LABELS: Record<VideoBatchStatus, string> = {
  PENDING_NARRATION_REVIEW: '等待节目口播审核',
  PENDING_BATCH_TTS: '等待批次语音合成',
  PROCESSING_BATCH_TTS: '合成批次语音中',
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
  if (status === 'RENDERING' || status === 'PROCESSING_BATCH_TTS') return 'info';
  return 'caution';
}

function newBatchForm(): CreateVideoBatch {
  return {title: '', subtitle: null, story_ids: [], max_stories: 5, bgm_track_id: null, bgm_volume: 0.12, bgm_loop: true};
}

function batchCanBeCancelled(status: VideoBatchStatus): boolean {
  return !['PROCESSING_BATCH_TTS', 'RENDERING', 'RENDERED', 'CANCELLED'].includes(status);
}

function BatchNarrationAudioPreview({batch}: {batch: VideoBatch}) {
  const batchId = batch.batch_id;
  const audio = batch.narration.audio;
  if (batchId === undefined || audio === null || audio === undefined) return null;

  const segments = new Map(batch.narration.script.segments.map((segment) => [segment.segment_id, segment]));
  return (
    <section className="review-form" style={{marginTop: 16}}>
      <div className="panel-header">
        <div>
          <p className="eyebrow">PROGRAM NARRATION AUDIO</p>
          <h3>试听节目旁白</h3>
        </div>
        <span className="metadata">revision {String(audio.revision)}</span>
      </div>
      <p className="review-help">逐段试听来源故事与串联词组成的节目旁白，再决定是否批准时间轴。</p>
      <div className="audio-list">
        {audio.clips.map((clip, index) => {
          const segment = segments.get(clip.segment_id);
          return (
            <article className="audio-row" key={clip.segment_id}>
              <div className="audio-copy">
                <span className="audio-index metadata">
                  <Headphones size={16} aria-hidden="true" /> {String(index + 1).padStart(2, '0')}
                </span>
                <p>{segment?.spoken_text ?? '对应的统一旁白脚本文本不可用。'}</p>
                <span className="metadata">
                  {(clip.duration_ms / 1000).toFixed(2)}s · {String(clip.sample_rate_hz)}Hz · {String(clip.channels)}ch
                </span>
              </div>
              <audio
                aria-label={`试听统一旁白第 ${String(index + 1)} 段`}
                controls
                preload="metadata"
                src={videoBatchAudioClipUrl(batchId, clip.segment_id)}
              >
                浏览器不支持音频播放。
              </audio>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ProgramDirectionSummary({batch}: {batch: VideoBatch}) {
  const direction = batch.narration.direction;
  if (direction === null || direction === undefined) return null;
  const titles = new Map(batch.stories.map((story) => [story.story_id, story.title]));

  return (
    <section style={{marginTop: 18}}>
      <div className="panel-header">
        <div><p className="eyebrow">PROGRAM DIRECTOR PLAN</p><h3>节目导演计划</h3></div>
        <span className="metadata">schema {direction.schema_version}</span>
      </div>
      <p className="field-hint">已审核故事段落保持原样；导演层只负责顺序、注册场景、原视频插入和相邻故事串联词。</p>
      <div className="table-container">
        <table className="table dense">
          <thead><tr><th>顺序</th><th>故事</th><th>场景</th><th>原视频</th></tr></thead>
          <tbody>
            {direction.stories.map((story, index) => (
              <tr key={story.story_id}>
                <td className="metadata">{String(index + 1).padStart(2, '0')}</td>
                <td>{titles.get(story.story_id) ?? story.story_id}</td>
                <td className="metadata">{story.narration_module}</td>
                <td className="metadata">{story.source_video_placement === 'after_story' ? '故事后播放' : '不插入'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="metadata">自然串联词：{String(direction.bridges?.length ?? 0)} 段</p>
    </section>
  );
}

interface BatchDetailProps {
  batch: VideoBatch;
  onDelete: (batchId: string) => void;
  onCancel: (batchId: string) => void;
  onNarrationReview: (
    batch: VideoBatch,
    decision: NarrationReviewDecision,
    revisedScript?: ScriptDocument,
    note?: string,
    reviewerId?: string,
  ) => void;
  onSynthesize: (batch: VideoBatch) => void;
  onTimelineReview: (batch: VideoBatch, decision: 'approve' | 'reject', note?: string, reviewerId?: string) => void;
  onRender: (batch: VideoBatch) => void;
  roles?: RoleProfile[];
  isMutating: boolean;
}

function BatchDetail({
  batch,
  onDelete,
  onCancel,
  onNarrationReview,
  onSynthesize,
  onTimelineReview,
  onRender,
  roles,
  isMutating,
}: BatchDetailProps) {
  const [script, setScript] = useState(batch.narration.script);
  const [reviewerId, setReviewerId] = useState('web-operator');
  const [note, setNote] = useState('');
  const [confirmSynthesis, setConfirmSynthesis] = useState(false);
  const batchId = batch.batch_id;
  const editableNarration = canEditNarration(batch.status);
  const canApproveNarration = batch.status === 'PENDING_NARRATION_REVIEW';
  const canSynthesize = batch.status === 'PENDING_BATCH_TTS';
  const canReviewTimeline = batch.status === 'PENDING_TIMELINE_REVIEW';
  const canPreviewNarration = canPreviewBatchNarration(
    batch.status,
    batch.narration.audio !== null && batch.narration.audio !== undefined,
  );
  const canRender = batch.status === 'READY_TO_RENDER' || batch.status === 'FAILED';
  const narrationChanged = JSON.stringify(script) !== JSON.stringify(batch.narration.script);
  const totalDuration = batch.narration.manifest?.total_duration_ms ?? 0;
  const segmentLabels: Record<string, string> = {};
  const storyTitles = new Map(batch.stories.map((story) => [story.story_id, story.title]));
  for (const story of batch.narration.direction?.stories ?? []) {
    for (const segmentId of story.source_segment_ids) {
      segmentLabels[segmentId] = `来源：${storyTitles.get(story.story_id) ?? story.story_id}`;
    }
  }
  for (const bridge of batch.narration.direction?.bridges ?? []) {
    segmentLabels[bridge.segment_id] = `串联：${storyTitles.get(bridge.from_story_id) ?? '上一条'} → ${storyTitles.get(bridge.to_story_id) ?? '下一条'}`;
  }

  return (
    <>
      {batch.artifact === undefined || batch.artifact === null ? null : (
        <section style={{marginBottom: 18}}>
          <div className="panel-header"><div><p className="eyebrow">RENDER OUTPUTS</p><h3>双平台成片</h3></div><span className="metadata">{batch.artifact.renderer}</span></div>
          {'outputs' in batch.artifact ? (
            <div className="info-grid">
              {batch.artifact.outputs.map((output) => (
                <div className="info-item" key={output.profile_id}>
                  <span className="label">{output.profile_id === 'douyin_vertical' ? '抖音 9:16' : 'Bilibili 16:9'}</span>
                  <span className="value">{output.width}×{output.height} · {output.fps}fps</span>
                  <span className="metadata">{output.video_codec} + {output.audio_codec} · {(output.size_bytes / 1024 / 1024).toFixed(2)} MiB</span>
                  {batch.batch_id === undefined ? null : <a className="button secondary" href={videoBatchOutputUrl(batch.batch_id, output.profile_id)} target="_blank" rel="noreferrer">播放成片</a>}
                </div>
              ))}
            </div>
          ) : (
            <p className="pending-note">旧版单输出成片已作为审计证据只读保留；它没有可下载的双平台输出。</p>
          )}
        </section>
      )}
      <div className="info-grid">
        <div className="info-item"><span className="label">状态</span><span className={`badge ${statusTone(batch.status)}`}>{STATUS_LABELS[batch.status]}</span></div>
        <div className="info-item"><span className="label">版本</span><span className="value">v{String(batch.version)}</span></div>
        <div className="info-item"><span className="label">来源故事</span><span className="value">{String(batch.stories.length)}</span></div>
        <div className="info-item"><span className="label">节目口播时长</span><span className="value">{totalDuration === 0 ? '待合成' : `${(totalDuration / 1000).toFixed(1)}s`}</span></div>
      </div>
      {batch.narration_failure === undefined || batch.narration_failure === null ? null : <div className="error-banner" style={{marginTop: 16}}><strong>旁白合成失败：</strong>{batch.narration_failure.message}</div>}
      {batch.last_failure === undefined || batch.last_failure === null ? null : <div className="error-banner" style={{marginTop: 16}}><strong>渲染失败：</strong>{batch.last_failure.message}</div>}

      <ProgramDirectionSummary batch={batch} />
      <section style={{marginTop: 18}}>
        <div className="panel-header"><div><p className="eyebrow">DIRECTED PROGRAM SCRIPT</p><h3>节目口播文本</h3></div><span className="metadata">revision {String(batch.narration.script.revision)}</span></div>
        <p className="field-hint">来源故事沿用已审核段落；带新段落 ID 的内容是导演生成的自然串联词。修改文本时必须保留段落身份与顺序。</p>
        <ScriptEditor script={script} onChange={setScript} roles={roles ?? []} readOnly={!editableNarration} structureLocked={batch.narration.direction !== null && batch.narration.direction !== undefined} segmentLabels={segmentLabels} />
      </section>

      {editableNarration ? (
        <section className="review-form" style={{marginTop: 16}}>
          <p className="eyebrow">NARRATION REVIEW</p>
          <h3>{batch.status === 'PENDING_NARRATION_REVIEW' ? '人工审核节目口播' : '时间轴后修订口播'}</h3>
          <label className="field"><span>审核人</span><input className="input" value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} /></label>
          <label className="field"><span>审核说明</span><textarea className="textarea compact" value={note} onChange={(event) => setNote(event.target.value)} /></label>
          {narrationChanged ? <p className="pending-note">当前口播有未提交修订。保存后会清除已生成的批次音频与时间轴。</p> : null}
          <div className="review-actions stacked">
            <button className="button secondary" type="button" disabled={isMutating || !narrationChanged} onClick={() => onNarrationReview(batch, 'revise', script, note, reviewerId)}>保存修订并回到口播审核</button>
            {canApproveNarration ? <button className="button primary" type="button" disabled={isMutating || narrationChanged} onClick={() => onNarrationReview(batch, 'approve', undefined, note, reviewerId)}><CheckCircle2 size={17} aria-hidden="true" /> 批准节目口播</button> : null}
            {canApproveNarration ? <button className="button danger" type="button" disabled={isMutating || note.trim() === '' || narrationChanged} onClick={() => onNarrationReview(batch, 'reject', undefined, note, reviewerId)}><XCircle size={17} aria-hidden="true" /> 驳回批次</button> : null}
          </div>
        </section>
      ) : null}

      {canSynthesize ? (
        <section className="review-form" style={{marginTop: 16}}><p className="eyebrow">LOCAL PROGRAM TTS</p><h3>手动合成节目口播</h3><p className="review-help">口播已批准。此操作会按已审核故事与串联词的角色、语言和情绪逐段执行本地 TTS。</p><button className="button primary" type="button" disabled={isMutating} onClick={() => setConfirmSynthesis(true)}><Mic2 size={17} aria-hidden="true" /> 启动批次 TTS</button></section>
      ) : null}
      {batch.status === 'PROCESSING_BATCH_TTS' ? <p className="pending-note" role="status">本地批次 TTS 正在运行，页面会自动刷新。</p> : null}
      {canPreviewNarration ? <BatchNarrationAudioPreview batch={batch} /> : null}
      {canReviewTimeline ? (
        <section className="review-form" style={{marginTop: 16}}><p className="eyebrow">TIMELINE REVIEW</p><h3>审阅合成后的时间轴</h3><p className="review-help">音频和统一 ProductionManifest 已就绪。若需改文案，请直接修订上方口播并回到审核门。</p><div className="review-actions"><button className="button primary" type="button" disabled={isMutating || narrationChanged} onClick={() => onTimelineReview(batch, 'approve', note, reviewerId)}><Clapperboard size={17} aria-hidden="true" /> 批准时间轴</button><button className="button danger" type="button" disabled={isMutating || note.trim() === '' || narrationChanged} onClick={() => onTimelineReview(batch, 'reject', note, reviewerId)}>驳回时间轴</button></div></section>
      ) : null}

      <div style={{marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
        {batchId === undefined || !canRender ? null : <button className="button primary" type="button" disabled={isMutating} onClick={() => onRender(batch)}><Film size={16} aria-hidden="true" /> 开始渲染</button>}
        {batchId === undefined || !batchCanBeCancelled(batch.status) ? null : <button className="button danger" type="button" disabled={isMutating} onClick={() => onCancel(batchId)}><Square size={15} aria-hidden="true" /> 取消批次</button>}
        {batchId === undefined || batch.status === 'PROCESSING_BATCH_TTS' || batch.status === 'RENDERING' || batch.status === 'RENDERED' ? null : <button className="button danger" type="button" disabled={isMutating} onClick={() => onDelete(batchId)}><Trash2 size={15} aria-hidden="true" /> 删除批次</button>}
      </div>

      <section style={{marginTop: 16}}>
        <h3>来源证据</h3>
        <div className="table-container" style={{maxHeight: 300, overflowY: 'auto'}}><table className="table dense"><thead><tr><th>故事</th><th>脚本版本</th><th>段数</th></tr></thead><tbody>{batch.stories.map((story) => <tr key={story.story_id}><td>{story.title}</td><td className="metadata">v{String(story.script.revision)}</td><td className="metadata">{String(story.script.segments.length)}</td></tr>)}</tbody></table></div>
      </section>
      <ConfirmDialog open={confirmSynthesis} title="启动批次本地 TTS" message="将为已审核节目口播生成一套新的批次音频和 ProductionManifest。请勿重复提交。" confirmLabel="启动合成" onConfirm={() => { onSynthesize(batch); setConfirmSynthesis(false); }} onCancel={() => setConfirmSynthesis(false)} />
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
  const rolesQuery = useQuery({queryKey: queryKeys.roles(), queryFn: () => listRoles(), enabled: selectedId !== null});
  const detailQuery = useQuery({
    queryKey: queryKeys.videoBatch(selectedId ?? ''),
    queryFn: () => getVideoBatch(selectedId ?? ''),
    enabled: selectedId !== null,
    refetchInterval: (state) => ['PROCESSING_BATCH_TTS', 'RENDERING'].includes(state.state.data?.status ?? '') ? 2_000 : false,
  });
  const refreshBatches = () => void queryClient.invalidateQueries({queryKey: queryKeys.videoBatches()});
  const refreshSelected = (batch: VideoBatch) => { if (batch.batch_id !== undefined) void queryClient.invalidateQueries({queryKey: queryKeys.videoBatch(batch.batch_id)}); };
  const createMutation = useMutation({
    mutationFn: createVideoBatch,
    onSuccess: (batch) => { refreshBatches(); setShowCreate(false); setCreateForm(newBatchForm()); if (batch.batch_id !== undefined) setSelectedId(batch.batch_id); pushToast({message: '批次已创建，请先审核导演计划和节目口播。', durationMs: 3000}); },
  });
  const narrationReviewMutation = useMutation({
    mutationFn: ({batch, decision, revisedScript, note, reviewerId}: {batch: VideoBatch; decision: NarrationReviewDecision; revisedScript?: ScriptDocument; note?: string; reviewerId?: string}) => {
      if (batch.batch_id === undefined) throw new Error('批次缺少标识。');
      return submitVideoBatchNarrationReview(batch.batch_id, {expected_batch_version: batch.version, decision, reviewer_id: reviewerId?.trim() || 'web-operator', note: note?.trim() || null, revised_script: revisedScript ?? null});
    },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '节目口播审核已保存。', durationMs: 3000}); },
  });
  const synthesizeMutation = useMutation({
    mutationFn: (batch: VideoBatch) => {
      if (batch.batch_id === undefined) throw new Error('批次缺少标识。');
      return synthesizeVideoBatchNarration(batch.batch_id, {expected_batch_version: batch.version});
    },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '批次本地 TTS 已完成，等待时间轴审核。', durationMs: 3000}); },
  });
  const timelineMutation = useMutation({
    mutationFn: ({batch, decision, note, reviewerId}: {batch: VideoBatch; decision: 'approve' | 'reject'; note?: string; reviewerId?: string}) => {
      if (batch.batch_id === undefined) throw new Error('批次缺少标识。');
      const body: SubmitTimelineReview = {expected_batch_version: batch.version, decision, reviewer_id: reviewerId?.trim() || 'web-operator', note: note?.trim() || null, story_order: batch.stories.map((story) => story.story_id)};
      return submitTimelineReview(batch.batch_id, body);
    },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '时间轴审核已保存。', durationMs: 3000}); },
  });
  const renderMutation = useMutation({
    mutationFn: (batch: VideoBatch) => { if (batch.batch_id === undefined) throw new Error('批次缺少标识。'); return renderVideoBatch(batch.batch_id, {expected_batch_version: batch.version}); },
    onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '渲染请求已提交。', durationMs: 3000}); },
  });
  const cancelMutation = useMutation({mutationFn: cancelVideoRender, onSuccess: (batch) => { refreshBatches(); refreshSelected(batch); pushToast({message: '批次已取消，故事占用已释放。', variant: 'caution', durationMs: 3000}); }});
  const deleteMutation = useMutation({mutationFn: deleteVideoBatch, onSuccess: () => { refreshBatches(); setDeleteTarget(null); setSelectedId(null); pushToast({message: '批次已删除，故事占用已释放。', variant: 'caution', durationMs: 3000}); }});
  const mutationError = createMutation.error ?? narrationReviewMutation.error ?? synthesizeMutation.error ?? timelineMutation.error ?? renderMutation.error ?? cancelMutation.error ?? deleteMutation.error;
  const batches = query.data ?? [];

  return (
    <div className="page video-page">
      <div className="page-heading"><div><p className="eyebrow">VIDEO PRODUCTION</p><h1>视频批次</h1><p>节目导演只编排已审核故事、注册场景、原视频和自然串联词；人工批准后才执行本地 TTS 与确定性双比例渲染。</p></div><button className="button primary" type="button" onClick={() => setShowCreate(true)} disabled={showCreate}><Plus size={18} aria-hidden="true" /> 新建批次</button></div>
      {query.isLoading ? <div className="loading-state">正在加载视频批次…</div> : query.error !== null ? <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} /> : batches.length === 0 ? <EmptyState title="尚无视频批次" description="创建批次会从可用的 DONE 故事生成一份可审核节目导演计划。" action={{label: '新建批次', onClick: () => setShowCreate(true)}} /> : <div className="table-container"><table className="table"><thead><tr><th>标题</th><th>状态</th><th>版本</th><th>创建时间</th><th className="actions-cell">操作</th></tr></thead><tbody>{batches.map((batch) => { const batchId = batch.batch_id; return <tr key={batchId ?? `${batch.title}-${batch.created_at ?? batch.version}`}><td><strong>{batch.title}</strong></td><td><span className={`badge ${statusTone(batch.status)}`}>{batch.status === 'RENDERING' || batch.status === 'PROCESSING_BATCH_TTS' ? <RefreshCw className="spinning" size={12} aria-hidden="true" /> : null} {STATUS_LABELS[batch.status]}</span></td><td>v{String(batch.version)}</td><td className="metadata">{batch.created_at ?? '—'}</td><td className="actions-cell">{batchId === undefined ? null : <button className="icon-button" type="button" aria-label="查看详情" onClick={() => setSelectedId(batchId)}><Eye size={16} aria-hidden="true" /></button>}</td></tr>; })}</tbody></table></div>}

      {selectedId === null ? null : <dialog className="create-drawer wide-drawer" open onCancel={(event) => { event.preventDefault(); setSelectedId(null); }}><div className="panel-header"><div><p className="eyebrow">BATCH DETAIL</p><h2>批次详情</h2></div><button className="icon-button" type="button" onClick={() => setSelectedId(null)} aria-label="关闭">✕</button></div><div className="panel-body">{detailQuery.isLoading ? <div className="loading-state">正在加载批次详情…</div> : detailQuery.error !== null ? <ApiErrorNotice error={detailQuery.error} onRetry={() => void detailQuery.refetch()} /> : detailQuery.data === undefined ? null : <BatchDetail key={`${detailQuery.data.batch_id ?? 'batch'}-${String(detailQuery.data.version)}`} batch={detailQuery.data} roles={rolesQuery.data} isMutating={narrationReviewMutation.isPending || synthesizeMutation.isPending || timelineMutation.isPending || renderMutation.isPending || cancelMutation.isPending || deleteMutation.isPending} onDelete={setDeleteTarget} onCancel={(batchId) => cancelMutation.mutate(batchId)} onNarrationReview={(batch, decision, revisedScript, note, reviewerId) => narrationReviewMutation.mutate({batch, decision, revisedScript, note, reviewerId})} onSynthesize={(batch) => synthesizeMutation.mutate(batch)} onTimelineReview={(batch, decision, note, reviewerId) => timelineMutation.mutate({batch, decision, note, reviewerId})} onRender={(batch) => renderMutation.mutate(batch)} />}{mutationError === null ? null : <ApiErrorNotice error={mutationError} />}</div></dialog>}

      {showCreate ? <dialog className="create-drawer" open onCancel={(event) => { event.preventDefault(); setShowCreate(false); }}><div className="panel-header"><div><p className="eyebrow">NEW BATCH</p><h2>新建视频批次</h2></div><button className="icon-button" type="button" onClick={() => setShowCreate(false)} aria-label="关闭">✕</button></div><form className="panel-body form-grid" onSubmit={(event) => { event.preventDefault(); createMutation.mutate(createForm); }}><label className="field wide"><span>标题</span><input className="input" required value={createForm.title} onChange={(event) => setCreateForm({...createForm, title: event.target.value})} /></label><label className="field wide"><span>副标题（可选）</span><input className="input" value={createForm.subtitle ?? ''} onChange={(event) => setCreateForm({...createForm, subtitle: event.target.value === '' ? null : event.target.value})} /></label><label className="field"><span>自动选择故事数</span><input className="input" type="number" min={1} max={15} value={createForm.max_stories} onChange={(event) => setCreateForm({...createForm, max_stories: Number(event.target.value)})} /></label><label className="field"><span>BGM（可选）</span><select className="select" value={createForm.bgm_track_id ?? ''} onChange={(event) => setCreateForm({...createForm, bgm_track_id: event.target.value === '' ? null : event.target.value})}><option value="">不使用 BGM</option>{bgmQuery.data?.map((track) => <option key={track.track_id} value={track.track_id}>{track.display_name}</option>)}</select></label><label className="field"><span>BGM 音量</span><input className="input" type="number" min={0} max={1} step={0.01} value={createForm.bgm_volume} onChange={(event) => setCreateForm({...createForm, bgm_volume: Number(event.target.value)})} /></label><label className="checkbox-field"><input type="checkbox" checked={createForm.bgm_loop} onChange={(event) => setCreateForm({...createForm, bgm_loop: event.target.checked})} /><span>BGM 循环</span></label>{createMutation.error === null ? null : <div className="wide"><ApiErrorNotice error={createMutation.error} /></div>}<div className="form-actions wide"><button className="button" type="button" onClick={() => setShowCreate(false)}>取消</button><button className="button primary" type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? '创建中…' : '创建并审阅口播'}</button></div></form></dialog> : null}
      <ConfirmDialog open={deleteTarget !== null} title="删除视频批次" message="未渲染批次会被删除并释放故事占用；已渲染的批次是不可删除的审计证据。" variant="danger" confirmLabel="确认删除" onConfirm={() => { if (deleteTarget !== null) deleteMutation.mutate(deleteTarget); }} onCancel={() => setDeleteTarget(null)} />
    </div>
  );
}
