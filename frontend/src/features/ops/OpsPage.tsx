import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Clock, RefreshCw, Trash2} from 'lucide-react';

import {listOperationRuns, listSchedules, triggerRetention} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {OperationRun} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EmptyState} from '../../components/EmptyState';
import {useToast} from '../../components/toastContext';

function formatDuration(run: OperationRun): string {
  if (run.finished_at === undefined || run.finished_at === null) return '进行中';
  const elapsed = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  return Number.isFinite(elapsed) && elapsed >= 0 ? `${(elapsed / 1000).toFixed(1)}s` : '—';
}

function runSummary(run: OperationRun): string {
  if (run.error !== undefined && run.error !== null) return run.error;
  if (run.result === undefined || run.result === null) return '—';
  const action = run.result.dry_run ? '演练' : '已清理';
  return `${action} ${String(run.result.deleted_count)} 个文件，回收 ${String(run.result.reclaimed_bytes)} 字节`;
}

export function OpsPage() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [showConfirmRetention, setShowConfirmRetention] = useState(false);

  const runsQuery = useQuery({
    queryKey: queryKeys.operationRuns(),
    queryFn: listOperationRuns,
    refetchInterval: 30_000,
  });
  const schedulesQuery = useQuery({
    queryKey: queryKeys.schedules(),
    queryFn: listSchedules,
    refetchInterval: 30_000,
  });
  const retentionMutation = useMutation({
    mutationFn: triggerRetention,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({queryKey: queryKeys.operationRuns()});
      if (data.result !== undefined && data.result !== null) {
        pushToast({
          message: `留存清理完成：删除 ${String(data.result.deleted_count)} 个文件，回收 ${String(data.result.reclaimed_bytes)} 字节。`,
          durationMs: 5000,
        });
      } else {
        pushToast({message: `留存清理未完成：${data.error ?? '请检查后端日志。'}`, variant: 'danger', durationMs: 5000});
      }
    },
    onError: () => {
      pushToast({message: '留存清理失败，请检查后端日志。', variant: 'danger', durationMs: 5000});
    },
  });

  return (
    <div className="page ops-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">OPERATIONS</p>
          <h1>运维日志</h1>
          <p>监控定时任务状态、手动触发文件留存清理，查看操作历史。</p>
        </div>
      </div>

      {/* Schedules */}
      <section className="panel" style={{marginBottom: 18}}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">SCHEDULES</p>
            <h2>定时调度</h2>
          </div>
          <RefreshCw className={schedulesQuery.isFetching ? 'spin' : ''} size={17} aria-hidden="true" style={{color: 'var(--ink-muted)'}} />
        </div>
        <div className="panel-body">
          {schedulesQuery.isLoading ? (
            <div className="loading-state">正在加载调度状态…</div>
          ) : schedulesQuery.error !== null ? (
            <ApiErrorNotice error={schedulesQuery.error} onRetry={() => void schedulesQuery.refetch()} />
          ) : schedulesQuery.data !== undefined && schedulesQuery.data.length === 0 ? (
            <EmptyState title="无定时调度" description="调度器未启用或未配置任何定时任务。在 .env 中设置 operations_scheduler_enabled=true。" />
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>操作类型</th>
                    <th>间隔</th>
                    <th>上次运行</th>
                    <th>下次运行</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {schedulesQuery.data?.map((schedule) => (
                    <tr key={schedule.schedule_id}>
                      <td><strong>{schedule.operation}</strong></td>
                      <td className="metadata">{String(schedule.interval_seconds)}s</td>
                      <td className="metadata">{schedule.last_run_status ?? '从未运行'}</td>
                      <td className="metadata">{schedule.next_run_at ?? '—'}</td>
                      <td>
                        <span className={`badge ${schedule.enabled ? 'success' : 'muted'}`}>
                          {schedule.enabled ? '运行中' : '已停用'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {/* Manual trigger */}
      <section className="panel" style={{marginBottom: 18}}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">MANUAL TRIGGER</p>
            <h2>手动操作</h2>
          </div>
        </div>
        <div className="panel-body">
          <p style={{marginBottom: 12, color: 'var(--ink-muted)'}}>
            <Clock size={16} aria-hidden="true" style={{verticalAlign: 'middle', marginRight: 6}} />
            过期文件将按配置的天数（素材 7 天 / 视频 3 天）自动清理。手动触发会立即执行一次清理。
          </p>
          <button
            className="button"
            type="button"
            disabled={retentionMutation.isPending}
            onClick={() => setShowConfirmRetention(true)}
          >
            <Trash2 size={17} aria-hidden="true" />
            {retentionMutation.isPending ? '清理中…' : '手动触发留存清理'}
          </button>
          {retentionMutation.isPending ? (
            <p className="pending-note" role="status" aria-live="polite" style={{marginTop: 12}}>
              正在扫描并清理过期文件。请勿关闭页面。
            </p>
          ) : null}
        </div>
      </section>

      {/* Operation history */}
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">HISTORY</p>
            <h2>操作历史</h2>
          </div>
        </div>
        <div className="panel-body">
          {runsQuery.isLoading ? (
            <div className="loading-state">正在加载操作记录…</div>
          ) : runsQuery.error !== null ? (
            <ApiErrorNotice error={runsQuery.error} onRetry={() => void runsQuery.refetch()} />
          ) : runsQuery.data !== undefined && runsQuery.data.length === 0 ? (
            <EmptyState title="暂无操作记录" description="手动触发一次留存清理后，记录将显示在此处。" />
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>操作类型</th>
                    <th>触发方式</th>
                    <th>状态</th>
                    <th>开始时间</th>
                    <th>耗时</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {runsQuery.data?.map((run) => (
                    <tr key={run.run_id ?? `${run.operation}-${run.started_at}`}>
                      <td><strong>{run.operation}</strong></td>
                      <td className="metadata">{run.origin}</td>
                      <td>
                        <span className={`badge ${run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'danger' : 'info'}`}>
                          {run.status}
                        </span>
                      </td>
                      <td className="metadata">{run.started_at}</td>
                      <td className="metadata">{formatDuration(run)}</td>
                      <td className="metadata">{runSummary(run)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={showConfirmRetention}
        title="手动触发留存清理"
        message="将扫描输出目录中超过保留期限的媒体文件和上传 MP4，并物理删除。建议先确认当前 .env 中的 retention 配置正确。"
        confirmLabel="执行清理"
        onConfirm={() => {
          setShowConfirmRetention(false);
          retentionMutation.mutate({
            operation: 'retention_cleanup',
            dry_run: false,
            requested_by: 'web-operator',
          });
        }}
        onCancel={() => setShowConfirmRetention(false)}
      />
    </div>
  );
}
