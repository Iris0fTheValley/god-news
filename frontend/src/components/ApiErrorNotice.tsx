import {AlertTriangle, RefreshCw} from 'lucide-react';

import {ApiProblem} from '../api/client';

interface ApiErrorNoticeProps {
  error: unknown;
  onRetry?: () => void;
}

export function ApiErrorNotice({error, onRetry}: ApiErrorNoticeProps) {
  const problem =
    error instanceof ApiProblem
      ? error
      : new ApiProblem(
          {
            code: 'client_error',
            message: error instanceof Error ? error.message : '发生了未知错误。',
            trace_id: 'client',
            story_id: null,
          },
          0,
        );
  return (
    <div className="error-banner" role="alert">
      <AlertTriangle size={20} aria-hidden="true" />
      <div>
        <strong>{problem.message}</strong>
        <span className="metadata">{problem.code}</span>
      </div>
      {onRetry === undefined ? null : (
        <button className="button" type="button" onClick={onRetry}>
          <RefreshCw size={17} aria-hidden="true" />
          重试
        </button>
      )}
    </div>
  );
}
