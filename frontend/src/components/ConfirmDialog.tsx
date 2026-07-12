import {AlertTriangle, X} from 'lucide-react';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '确认',
  cancelLabel = '取消',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      className="confirm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      onClick={onCancel}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel();
      }}
    >
      <div
        className="confirm-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-header">
          <div>
            <p className="eyebrow">{variant === 'danger' ? '⚠ 不可逆操作' : '操作确认'}</p>
            <h2 id="confirm-dialog-title">{title}</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onCancel}
            aria-label="关闭"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="panel-body">
          {variant === 'danger' ? (
            <div style={{display: 'flex', alignItems: 'flex-start', gap: '10px'}}>
              <AlertTriangle size={20} style={{color: 'var(--danger)', flexShrink: 0, marginTop: 3}} />
              <p>{message}</p>
            </div>
          ) : (
            <p>{message}</p>
          )}
        </div>
        <div className="form-actions" style={{padding: '0 18px 16px'}}>
          <button className="button" type="button" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            className={`button ${variant === 'danger' ? 'danger' : 'primary'}`}
            type="button"
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
