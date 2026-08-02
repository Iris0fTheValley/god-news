import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Power, RotateCw} from 'lucide-react';
import {useState} from 'react';

import {
  getRuntimeControlStatus,
  requestRuntimeAction,
  type RuntimeAction,
} from '../api/client';
import {queryKeys} from '../api/queryKeys';
import {ModalDialog} from './ModalDialog';
import {useToast} from './toastContext';

const ACTION_COPY: Record<RuntimeAction, {
  title: string;
  description: string;
  confirm: string;
}> = {
  restart: {
    title: '重启后端',
    description: '当前请求会完成后优雅停止后端，前台监督器随后启动一个全新进程。',
    confirm: '确认重启',
  },
  shutdown: {
    title: '关闭后端',
    description: '当前请求会完成后停止后端和开发前端；需要再次运行 start.cmd 才能恢复。',
    confirm: '确认关闭',
  },
};

export function RuntimeControls() {
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [pendingConfirmation, setPendingConfirmation] = useState<RuntimeAction | null>(null);
  const statusQuery = useQuery({
    queryKey: queryKeys.runtimeControl,
    queryFn: getRuntimeControlStatus,
    refetchInterval: 15_000,
    retry: false,
  });
  const actionMutation = useMutation({
    mutationFn: requestRuntimeAction,
    onSuccess: (receipt) => {
      setPendingConfirmation(null);
      pushToast({
        message: receipt.action === 'restart'
          ? '后端已接受重启命令，正在重新连接。'
          : '后端已接受关闭命令。',
        variant: 'default',
        durationMs: 5_000,
      });
      window.setTimeout(() => {
        void queryClient.invalidateQueries({queryKey: queryKeys.runtimeControl});
        void queryClient.invalidateQueries({queryKey: queryKeys.readiness});
      }, 2_000);
    },
  });
  const runtimeAvailable = statusQuery.data?.enabled === true
    && statusQuery.data.supervised === true;
  const busy = actionMutation.isPending
    || statusQuery.data?.pending_action !== null && statusQuery.data?.pending_action !== undefined;
  const unavailableReason = statusQuery.isLoading
    ? '正在检查后端控制能力'
    : runtimeAvailable
      ? undefined
      : '仅通过前台 start.cmd 启动时可用';
  const copy = pendingConfirmation === null ? null : ACTION_COPY[pendingConfirmation];

  return (
    <>
      <div className="runtime-controls" aria-label="后端控制">
        <button
          className="icon-button runtime-control"
          type="button"
          aria-label="重启后端"
          title={unavailableReason ?? '重启后端'}
          disabled={!runtimeAvailable || busy}
          onClick={() => setPendingConfirmation('restart')}
        >
          <RotateCw size={16} aria-hidden="true" />
        </button>
        <button
          className="icon-button runtime-control danger"
          type="button"
          aria-label="关闭后端"
          title={unavailableReason ?? '关闭后端'}
          disabled={!runtimeAvailable || busy}
          onClick={() => setPendingConfirmation('shutdown')}
        >
          <Power size={16} aria-hidden="true" />
        </button>
      </div>
      <ModalDialog
        open={pendingConfirmation !== null}
        className="confirm-dialog"
        labelledBy="runtime-confirmation-title"
        onClose={() => {
          if (!actionMutation.isPending) setPendingConfirmation(null);
        }}
      >
        <div className="confirm-dialog-content">
          <p className="eyebrow">LOCAL RUNTIME</p>
          <h2 id="runtime-confirmation-title">{copy?.title}</h2>
          <p>{copy?.description}</p>
          <div className="form-actions">
            <button
              className="button"
              type="button"
              disabled={actionMutation.isPending}
              onClick={() => setPendingConfirmation(null)}
            >
              取消
            </button>
            <button
              className={`button ${pendingConfirmation === 'shutdown' ? 'danger' : 'primary'}`}
              type="button"
              disabled={actionMutation.isPending || pendingConfirmation === null}
              onClick={() => {
                if (pendingConfirmation !== null) actionMutation.mutate(pendingConfirmation);
              }}
            >
              {actionMutation.isPending ? '正在提交…' : copy?.confirm}
            </button>
          </div>
        </div>
      </ModalDialog>
    </>
  );
}
