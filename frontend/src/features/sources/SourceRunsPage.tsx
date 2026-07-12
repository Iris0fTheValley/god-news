import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {AlertTriangle, CheckCircle2, Clock, Eye, Info, Play, RefreshCw, XCircle} from 'lucide-react';
import {useState} from 'react';

import {getSourceRun, listSourceRuns, startSourceRun} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/Toast';

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  collecting: '采集中',
  ingesting: '导入中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

function statusTone(status: string): string {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'cancelled') return 'muted';
  if (status === 'collecting' || status === 'ingesting') return 'info';
  return 'info';
}

export function SourceRunsPage() {
  const {push: pushToast} = useToast();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.sourceRuns(),
    queryFn: listSourceRuns,
    refetchInterval: 10_000,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.sourceRun(selectedRunId ?? ''),
    queryFn: () => getSourceRun(selectedRunId!),
    enabled: selectedRunId !== null,
  });

  const runs = (listQuery.data as unknown[]) ?? [];

  return (
    <div className="page source-runs-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">COLLECTION LOG</p>
          <h1>采集运行</h1>
          <p>查看每次数据源抓取的运行记录——状态、耗时、采集结果与错误详情。</p>
        </div>
      </div>

      {listQuery.isLoading ? (
        <div className="loading-state">正在加载运行记录…</div>
      ) : listQuery.error !== null ? (
        <ApiErrorNotice error={listQuery.error} onRetry={() => void listQuery.refetch()} />
      ) : runs.length === 0 ? (
        <EmptyState title="尚无采集运行记录" description="在后端触发一次自动采集，或点击「开始采集」手动启动。" action={{label: '开始采集', onClick: () => pushToast({message: '采集运行可通过后端调度器自动触发，或手动调用 POST /source-runs。', durationMs: 3000})}} />
      ) : (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>来源</th>
                <th>状态</th>
                <th>结果</th>
                <th>开始时间</th>
                <th>耗时</th>
                <th className="actions-cell">操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run: any) => {
                const runId = String(run['run_id'] ?? '');
                const status = String(run['status'] ?? '');
                const isRunning = status === 'collecting' || status === 'ingesting';
                return (
                  <tr key={runId}>
                    <td className="metadata">{String(run['request']?.['source'] ?? run['source'] ?? '—')}</td>
                    <td>
                      <span className={`badge ${statusTone(status)}`}>
                        {isRunning ? <RefreshCw className="spinning" size={12} aria-hidden="true" /> : null}
                        {' '}{STATUS_LABELS[status] ?? status}
                      </span>
                    </td>
                    <td className="metadata">
                      成功 {String(run['ingested_count'] ?? 0)} / 失败 {String(run['failed_count'] ?? 0)}
                      {run['duplicate_count'] != null && Number(run['duplicate_count']) > 0 ? ` / 重复 ${String(run['duplicate_count'])}` : ''}
                    </td>
                    <td className="metadata">{String(run['started_at'] ?? '—')}</td>
                    <td className="metadata">{run['duration_ms'] != null ? `${(Number(run['duration_ms']) / 1000).toFixed(1)}s` : '—'}</td>
                    <td className="actions-cell">
                      <button className="icon-button" type="button" aria-label="查看详情" onClick={() => setSelectedRunId(runId)}>
                        <Eye size={16} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selectedRunId !== null ? (
        <dialog className="create-drawer wide-drawer" open onCancel={(e) => { e.preventDefault(); setSelectedRunId(null); }}>
          <div className="panel-header">
            <div>
              <p className="eyebrow">RUN DETAIL</p>
              <h2>运行详情</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setSelectedRunId(null)} aria-label="关闭">✕</button>
          </div>
          <div className="panel-body">
            {detailQuery.isLoading ? (
              <div className="loading-state">正在加载运行详情…</div>
            ) : detailQuery.error !== null ? (
              <ApiErrorNotice error={detailQuery.error} onRetry={() => void detailQuery.refetch()} />
            ) : detailQuery.data !== undefined ? ((detail: any) => {
              const status = String(detail['status'] ?? '');
              const itemResults: any[] = detail['item_results'] ?? [];
              const collectionErrors: any[] = detail['collection_errors'] ?? [];
              const request: any = detail['request'] ?? {};
              const collectorOutcome: any = detail['collector_outcome'] ?? null;
              const runError: any = detail['run_error'] ?? null;

              return (
                <>
                  <div className="info-grid" style={{marginBottom: 16}}>
                    <div className="info-item">
                      <span className="label">来源</span>
                      <span className="value">{String(request['source'] ?? '—')}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">状态</span>
                      <span className={`badge ${statusTone(status)}`}>{STATUS_LABELS[status] ?? status}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">限制条数</span>
                      <span className="value">{String(request['limit'] ?? '—')}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">目标语言</span>
                      <span className="value">{String(request['target_language'] ?? '—')}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">发现条目</span>
                      <span className="value">{String(detail['items_discovered'] ?? 0)}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">失败率</span>
                      <span className="value">
                        {detail['failure_rate'] != null
                          ? `${(Number(detail['failure_rate']) * 100).toFixed(1)}%`
                          : itemResults.length === 0 ? 'N/A' : '0%'}
                      </span>
                    </div>
                    <div className="info-item">
                      <span className="label">开始时间</span>
                      <span className="value">{String(detail['started_at'] ?? '—')}</span>
                    </div>
                    <div className="info-item">
                      <span className="label">结束时间</span>
                      <span className="value">{String(detail['finished_at'] ?? '—')}</span>
                    </div>
                  </div>

                  {collectionErrors.length > 0 ? (
                    <section style={{marginBottom: 16}}>
                      <h3 style={{color: 'var(--color-semantic-danger)', display: 'flex', alignItems: 'center', gap: 6}}>
                        <AlertTriangle size={16} aria-hidden="true" /> 采集错误 ({collectionErrors.length})
                      </h3>
                      <ul className="error-list">
                        {collectionErrors.map((err: any, i: number) => (
                          <li key={i} className="error-item">
                            <code className="failure-code">{String(err['code'] ?? 'UNKNOWN')}</code>
                            <p>{String(err['message'] ?? '无详情')}</p>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}

                  {runError !== null ? (
                    <div className="error-banner" style={{marginBottom: 16}}>
                      <AlertTriangle size={16} aria-hidden="true" />
                      <div>
                        <strong>运行级错误</strong>
                        <code className="failure-code">{String(runError['code'] ?? 'UNKNOWN')}</code>
                        <p>{String(runError['message'] ?? '')}</p>
                      </div>
                    </div>
                  ) : null}

                  {collectorOutcome !== null ? (
                    <section style={{marginBottom: 16}}>
                      <h3>采集器结果</h3>
                      <div className="code-block">{JSON.stringify(collectorOutcome, null, 2)}</div>
                    </section>
                  ) : null}

                  {itemResults.length > 0 ? (
                    <section>
                      <h3>条目详情 ({itemResults.length})</h3>
                      <div className="table-container" style={{maxHeight: 360, overflowY: 'auto'}}>
                        <table className="table dense">
                          <thead>
                            <tr>
                              <th>外部 ID</th>
                              <th>结果</th>
                              <th>故事 ID</th>
                              <th>错误码</th>
                            </tr>
                          </thead>
                          <tbody>
                            {itemResults.map((item: any, i: number) => {
                              const outcome = String(item['outcome'] ?? '');
                              const outcomeIcon = outcome === 'ingested'
                                ? <CheckCircle2 size={14} />
                                : outcome === 'duplicate'
                                  ? <Info size={14} />
                                  : <XCircle size={14} />;
                              const outcomeTone = outcome === 'ingested' ? 'success'
                                : outcome === 'duplicate' ? 'info' : 'danger';
                              return (
                                <tr key={i}>
                                  <td className="metadata">{String(item['external_id'] ?? '—')}</td>
                                  <td><span className={`badge ${outcomeTone}`}>{outcomeIcon} {outcome}</span></td>
                                  <td className="metadata">{item['story_id'] != null ? String(item['story_id']).slice(0, 8) + '…' : '—'}</td>
                                  <td className="metadata">{item['error_code'] != null ? String(item['error_code']) : '—'}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  ) : status === 'collecting' || status === 'ingesting' ? (
                    <div className="progress-indicator" role="status" aria-live="polite">
                      <RefreshCw className="spinning" size={18} aria-hidden="true" />
                      <p>运行中…已发现 {String(detail['items_discovered'] ?? 0)} 条，页面每 10 秒刷新。</p>
                    </div>
                  ) : (
                    <p className="empty-state">此运行尚未产生条目结果。</p>
                  )}

                  <div className="form-actions wide" style={{marginTop: 16}}>
                    <button className="button" type="button" onClick={() => setSelectedRunId(null)}>关闭</button>
                  </div>
                </>
              );
            })(detailQuery.data) : null}
          </div>
        </dialog>
      ) : null}
    </div>
  );
}
