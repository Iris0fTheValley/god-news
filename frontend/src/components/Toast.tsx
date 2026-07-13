import {X} from 'lucide-react';
import {useCallback, useEffect, useState} from 'react';

import {ToastContext, type ToastItem} from './toastContext';

export function ToastProvider({children}: {children: React.ReactNode}) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const push = useCallback((item: Omit<ToastItem, 'id' | 'createdAt'>) => {
    const id = crypto.randomUUID();
    const createdAt = Date.now();
    setToasts((prev) => [...prev, {...item, id, createdAt}]);
    return id;
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Auto-dismiss
  useEffect(() => {
    if (toasts.length === 0) return;
    const interval = setInterval(() => {
      const now = Date.now();
      setToasts((prev) => prev.filter((t) => now - t.createdAt < t.durationMs));
    }, 500);
    return () => clearInterval(interval);
  }, [toasts.length]);

  return (
    <ToastContext.Provider value={{toasts, push, dismiss}}>
      {children}
      {toasts.length === 0 ? null : (
        <div className="toast-container" aria-live="polite" role="status">
          {toasts.map((toast) => (
            <div key={toast.id} className={`toast ${toast.variant ?? 'default'}`}>
              <div className="toast-message">{toast.message}</div>
              {toast.action !== undefined ? (
                <button className="toast-action" type="button" onClick={toast.action.onClick}>
                  {toast.action.label}
                </button>
              ) : null}
              <button
                className="toast-dismiss"
                type="button"
                aria-label="关闭通知"
                onClick={() => dismiss(toast.id)}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}
