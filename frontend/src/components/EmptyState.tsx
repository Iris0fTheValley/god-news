import {Inbox} from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: {label: string; onClick: () => void};
  icon?: React.ReactNode;
}

export function EmptyState({title, description, action, icon}: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon ?? <Inbox size={40} strokeWidth={1.5} aria-hidden="true" />}
      <h2>{title}</h2>
      {description !== undefined ? <p>{description}</p> : null}
      {action !== undefined ? (
        <button className="button primary" type="button" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
