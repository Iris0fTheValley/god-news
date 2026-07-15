import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {AlertTriangle, CheckCircle2, Eye, Info, Pause, Play, RefreshCw, Square, XCircle} from 'lucide-react';
import {useState} from 'react';

import {
  cancelSourceRun,
  getSourceRun,
  getSourceSchedule,
  listSourceRuns,
  startSourceRun,
  startSourceSchedule,
  stopSourceSchedule,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {SourceRun, SourceRunRequest, SourceRunStatus} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/toastContext';

const STATUS_LABELS: Record<SourceRunStatus, string> = {
  queued: '排队中',
  collecting: '采集中',
  ingesting: '导入中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

function statusTone(status: SourceRunStatus): string {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'muted';
  return 'info';
}

function formatElapsed(startedAt?: string | null, finishedAt?: string | null): string {
  if (startedAt === undefined || startedAt === null) return '—';
  if (finishedAt === undefined || finishedAt === null) return '进行中';
  const elapsed = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  return Number.isFinite(elapsed) && elapsed >= 0 ? `${(elapsed / 1000).toFixed(1)}s` : '—';
}

function initialRequest(): SourceRunRequest {
  return {
    source: 'guardian',
    limit: 10,
    target_language: 'zh-CN',
    style: 'clear, accurate short-video narration',
    target_duration_seconds: 90,
    speaker_id: 'narrator',
    emotion: 'happiness',
    speed: 1,
    pitch: 0,
    requested_by: 'web-operator',
  };
}

function canCancel(status: SourceRunStatus): boolean {
  return status === 'queued' || status === 'collecting' || status === 'ingesting';
}

function RunDetail({detail, onClose, onCancel}: {
  detail: SourceRun;
  onClose: () => void;
  onCancel: (runId: string) => void;
}) {
  const itemResults = detail.item_results ?? [];
  const collectionErrors = detail.collection_errors ?? [];
  const runId = detail.run_id;

  return (
    <>
      <div className="info-grid" style={{marginBottom: 16}}>
        <div className="info-item"><span className="label">来源</span><span className="value">{detail.request.source}</span></div>
        <div className="info-item"><span className="label">状态</span><span className={`badge ${statusTone(detail.status)}`}>{STATUS_LABELS[detail.status]}</span></div>
        <div className="info-item"><span className="label">限制条数</span><span className="value">{String(detail.request.limit)}</span></div>
        <div className="info-item"><span className="label">目标语言</span><span className="value">{detail.request.target_language}</span></div>
        <div className="info-item"><span className="label">发现条目</span><span className="value">{String(detail.items_discovered)}</span></div>
        <div className="info-item"><span className="label">失败率</span><span className="value">{detail.failure_rate === null ? 'N/A' : `${(detail.failure_rate * 100).toFixed(1)}%`}</span></div>
        <div className="info-item"><span className="label">开始时间</span><span className="value">{detail.started_at ?? '—'}</span></div>
        <div className="info-item"><span className="label">结束时间</span><span className="value">{detail.finished_at ?? '—'}</span></div>
      </div>

      {detail.status === 'ingesting' && detail.current_item_index !== null && detail.current_item_index !== undefined ? (
        <section className="source-policy-note" style={{marginBottom: 16}} aria-live="polite">
          <RefreshCw className="spinning" size={18} aria-hidden="true" />
          <div>
            <strong>正在处理 {String(detail.current_item_index)} / {String(detail.items_discovered)}</strong>
            <p>{detail.current_title ?? detail.current_external_id ?? '未命名条目'}</p>
            {detail.current_url === null || detail.current_url === undefined ? null : (
              <p className="metadata">{detail.current_url}</p>
            )}
          </div>
        </section>
      ) : null}

      {collectionErrors.length > 0 ? (
        <section style={{marginBottom: 16}}>
          <h3 style={{color: 'var(--color-semantic-danger)', display: 'flex', alignItems: 'center', gap: 6}}>
            <AlertTriangle size={16} aria-hidden="true" /> 采集错误 ({String(collectionErrors.length)})
          </h3>
          <ul className="error-list">
            {collectionErrors.map((error) => (
              <li key={`${error.code}-${error.message}`} className="error-item">
                <code className="failure-code">{error.code}</code>
                <p>{error.message}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {detail.run_error === undefined || detail.run_error === null ? null : (
        <div className="error-banner" style={{marginBottom: 16}}>
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <strong>运行级错误</strong>
            <code className="failure-code">{detail.run_error.code}</code>
            <p>{detail.run_error.message}</p>
          </div>
        </div>
      )}

      {detail.collector_outcome === undefined || detail.collector_outcome === null ? null : (
        <section style={{marginBottom: 16}}>
          <h3>采集器结果</h3>
          <div className="code-block">{detail.collector_outcome}</div>
        </section>
      )}

      {itemResults.length > 0 ? (
        <section>
          <h3>条目详情 ({String(itemResults.length)})</h3>
          <div className="table-container" style={{maxHeight: 360, overflowY: 'auto'}}>
            <table className="table dense">
              <thead><tr><th>外部 ID</th><th>结果</th><th>故事 ID</th><th>错误码</th></tr></thead>
              <tbody>
                {itemResults.map((item) => {
                  const outcomeIcon = item.outcome === 'ingested'
                    ? <CheckCircle2 size={14} />
                    : item.outcome === 'duplicate' ? <Info size={14} /> : <XCircle size={14} />;
                  const outcomeTone = item.outcome === 'ingested' ? 'success'
                    : item.outcome === 'duplicate' ? 'info' : 'danger';
                  return (
                    <tr key={item.external_id}>
                      <td className="metadata">{item.external_id}</td>
                      <td><span className={`badge ${outcomeTone}`}>{outcomeIcon} {item.outcome}</span></td>
                      <td className="metadata">{item.story_id === undefined || item.story_id === null ? '—' : `${item.story_id.slice(0, 8)}…`}</td>
                      <td className="metadata">{item.error_code ?? '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : canCancel(detail.status) ? (
        <div className="progress-indicator" role="status" aria-live="polite">
          <RefreshCw className="spinning" size={18} aria-hidden="true" />
          <p>运行中…已发现 {String(detail.items_discovered)} 条，页面每 10 秒刷新。</p>
        </div>
      ) : <p className="empty-state">此运行尚未产生条目结果。</p>}

      <div className="form-actions wide" style={{marginTop: 16}}>
        <button className="button" type="button" onClick={onClose}>关闭</button>
        {runId !== undefined && canCancel(detail.status) ? (
          <button className="button danger" type="button" onClick={() => onCancel(runId)}>
            <Square size={15} aria-hidden="true" /> 取消运行
          </button>
        ) : null}
      </div>
    </>
  );
}

export function SourceRunsPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [startOpen, setStartOpen] = useState(false);
  const [request, setRequest] = useState<SourceRunRequest>(initialRequest);
  const [cancelTarget, setCancelTarget] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.sourceRuns(),
    queryFn: () => listSourceRuns(),
    refetchInterval: 10_000,
  });
  const scheduleQuery = useQuery({
    queryKey: queryKeys.sourceSchedule(),
    queryFn: getSourceSchedule,
    refetchInterval: 10_000,
  });
  const detailQuery = useQuery({
    queryKey: queryKeys.sourceRun(selectedRunId ?? ''),
    queryFn: () => getSourceRun(selectedRunId ?? ''),
    enabled: selectedRunId !== null,
    refetchInterval: (state) => state.state.data !== undefined && canCancel(state.state.data.status) ? 5_000 : false,
  });
  const startMutation = useMutation({
    mutationFn: startSourceRun,
    onSuccess: (run) => {
      void queryClient.invalidateQueries({queryKey: queryKeys.sourceRuns()});
      setStartOpen(false);
      setRequest(initialRequest());
      if (run.run_id !== undefined) setSelectedRunId(run.run_id);
      pushToast({message: '采集运行已入队。', durationMs: 3000});
    },
  });
  const cancelMutation = useMutation({
    mutationFn: cancelSourceRun,
    onSuccess: (run) => {
      void queryClient.invalidateQueries({queryKey: queryKeys.sourceRuns()});
      if (run.run_id !== undefined) void queryClient.invalidateQueries({queryKey: queryKeys.sourceRun(run.run_id)});
      setCancelTarget(null);
      pushToast({message: '采集运行已取消并保留审计记录。', variant: 'caution', durationMs: 3000});
    },
  });
  const scheduleMutation = useMutation({
    mutationFn: (enable: boolean) => enable ? startSourceSchedule() : stopSourceSchedule(),
    onSuccess: (schedule) => {
      queryClient.setQueryData(queryKeys.sourceSchedule(), schedule);
      void queryClient.invalidateQueries({queryKey: queryKeys.sourceRuns()});
      pushToast({
        message: schedule.enabled
          ? '自动采集已启动；只会运行已就绪的来源。'
          : '自动采集已停止；当前运行不会被强制中断。',
        variant: schedule.enabled ? undefined : 'caution',
        durationMs: 4000,
      });
    },
  });

  const runs = listQuery.data ?? [];

  return (
    <div className="page source-runs-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">COLLECTION LOG</p>
          <h1>采集运行</h1>
          <p>每次运行都记录抓取尝试、导入结果与错误证据；取消不会抹掉已完成的工作。</p>
        </div>
        <button className="button primary" type="button" onClick={() => setStartOpen(true)}>
          <Play size={17} aria-hidden="true" /> 开始采集
        </button>
      </div>

      {scheduleQuery.error !== null ? (
        <ApiErrorNotice error={scheduleQuery.error} onRetry={() => void scheduleQuery.refetch()} />
      ) : scheduleQuery.data === undefined ? (
        <div className="loading-state">正在加载自动采集状态…</div>
      ) : (
        <section className="source-policy-note" aria-live="polite">
          <div>
            <strong>自动采集：{scheduleQuery.data.enabled ? '运行中' : '已停止'}</strong>
            <p>
              {scheduleQuery.data.enabled
                ? `已就绪来源 ${String(scheduleQuery.data.ready_sources.length)} 个；当前运行 ${String(scheduleQuery.data.active_runs.length)} 个。`
                : '服务启动不会自行持续抓取；手动采集仍可独立使用。'}
            </p>
            {scheduleQuery.data.enabled && scheduleQuery.data.next_run_at !== null ? (
              <p className="metadata">下一轮：{scheduleQuery.data.next_run_at}</p>
            ) : null}
          </div>
          <button
            className={`button ${scheduleQuery.data.enabled ? '' : 'primary'}`}
            type="button"
            disabled={scheduleMutation.isPending}
            onClick={() => scheduleMutation.mutate(!scheduleQuery.data.enabled)}
          >
            {scheduleQuery.data.enabled ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
            {scheduleMutation.isPending ? '处理中…' : scheduleQuery.data.enabled ? '停止自动采集' : '启动自动采集'}
          </button>
        </section>
      )}

      {listQuery.isLoading ? <div className="loading-state">正在加载运行记录…</div>
        : listQuery.error !== null ? <ApiErrorNotice error={listQuery.error} onRetry={() => void listQuery.refetch()} />
          : runs.length === 0 ? (
            <EmptyState title="尚无采集运行记录" description="选择一个已授权的数据源后启动采集。" action={{label: '开始采集', onClick: () => setStartOpen(true)}} />
          ) : (
            <div className="table-container">
              <table className="table">
                <thead><tr><th>来源</th><th>状态</th><th>结果</th><th>开始时间</th><th>耗时</th><th className="actions-cell">操作</th></tr></thead>
                <tbody>
                  {runs.map((run) => {
                    const runId = run.run_id;
                    return (
                      <tr key={runId ?? `${run.request.source}-${run.created_at ?? run.version}`}>
                        <td className="metadata">{run.request.source}</td>
                        <td><span className={`badge ${statusTone(run.status)}`}>{canCancel(run.status) ? <RefreshCw className="spinning" size={12} aria-hidden="true" /> : null} {STATUS_LABELS[run.status]}</span></td>
                        <td className="metadata">成功 {String(run.ingested_count)} / 失败 {String(run.failed_count)}{run.duplicate_count > 0 ? ` / 重复 ${String(run.duplicate_count)}` : ''}</td>
                        <td className="metadata">{run.started_at ?? '—'}</td>
                        <td className="metadata">{formatElapsed(run.started_at, run.finished_at)}</td>
                        <td className="actions-cell">
                          {runId === undefined ? null : <button className="icon-button" type="button" aria-label="查看详情" onClick={() => setSelectedRunId(runId)}><Eye size={16} aria-hidden="true" /></button>}
                          {runId === undefined || !canCancel(run.status) ? null : <button className="icon-button danger" type="button" aria-label="取消运行" onClick={() => setCancelTarget(runId)}><Square size={15} aria-hidden="true" /></button>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

      {selectedRunId === null ? null : (
        <dialog className="create-drawer wide-drawer" open onCancel={(event) => { event.preventDefault(); setSelectedRunId(null); }}>
          <div className="panel-header"><div><p className="eyebrow">RUN DETAIL</p><h2>运行详情</h2></div><button className="icon-button" type="button" onClick={() => setSelectedRunId(null)} aria-label="关闭">✕</button></div>
          <div className="panel-body">
            {detailQuery.isLoading ? <div className="loading-state">正在加载运行详情…</div>
              : detailQuery.error !== null ? <ApiErrorNotice error={detailQuery.error} onRetry={() => void detailQuery.refetch()} />
                : detailQuery.data === undefined ? null : <RunDetail detail={detailQuery.data} onClose={() => setSelectedRunId(null)} onCancel={setCancelTarget} />}
          </div>
        </dialog>
      )}

      {startOpen ? (
        <dialog className="create-drawer" open onCancel={(event) => { event.preventDefault(); setStartOpen(false); }}>
          <div className="panel-header"><div><p className="eyebrow">START COLLECTION</p><h2>开始采集</h2></div><button className="icon-button" type="button" onClick={() => setStartOpen(false)} aria-label="关闭">✕</button></div>
          <form className="panel-body form-grid" onSubmit={(event) => { event.preventDefault(); startMutation.mutate(request); }}>
            <label className="field"><span>来源</span><select className="select" value={request.source} onChange={(event) => setRequest({...request, source: event.target.value as SourceRunRequest['source']})}><option value="guardian">Guardian</option><option value="reddit">Reddit</option><option value="dazhong">大众网</option><option value="pikabu">Pikabu</option></select></label>
            <label className="field"><span>条数上限</span><input className="input" type="number" min={1} max={50} value={request.limit} onChange={(event) => setRequest({...request, limit: Number(event.target.value)})} /></label>
            <label className="field"><span>目标语言</span><input className="input" value={request.target_language} onChange={(event) => setRequest({...request, target_language: event.target.value})} /></label>
            <label className="field"><span>请求人</span><input className="input" value={request.requested_by} onChange={(event) => setRequest({...request, requested_by: event.target.value})} /></label>
            {startMutation.error === null ? null : <div className="wide"><ApiErrorNotice error={startMutation.error} /></div>}
            <div className="form-actions wide"><button className="button" type="button" onClick={() => setStartOpen(false)}>取消</button><button className="button primary" type="submit" disabled={startMutation.isPending}>{startMutation.isPending ? '提交中…' : '启动'}</button></div>
          </form>
        </dialog>
      ) : null}

      <ConfirmDialog
        open={cancelTarget !== null}
        title="取消采集运行"
        message="当前任务会停止继续抓取和导入；已完成的条目及取消原因会保留在审计记录中。"
        variant="danger"
        confirmLabel="确认取消"
        onConfirm={() => { if (cancelTarget !== null) cancelMutation.mutate(cancelTarget); }}
        onCancel={() => setCancelTarget(null)}
      />
    </div>
  );
}
