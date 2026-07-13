import {createContext, useContext} from 'react';

export interface ToastItem {
  id: string;
  message: string;
  variant?: 'default' | 'danger' | 'caution';
  action?: {label: string; onClick: () => void};
  durationMs: number;
  createdAt: number;
}

export interface ToastContextValue {
  toasts: ToastItem[];
  push: (toast: Omit<ToastItem, 'id' | 'createdAt'>) => string;
  dismiss: (id: string) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context === null) throw new Error('useToast must be used within ToastProvider');
  return context;
}
