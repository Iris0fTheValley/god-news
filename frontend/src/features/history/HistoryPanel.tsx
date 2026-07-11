import type {ReviewRecord, StateTransition} from '../../api/types';
import {STATUS_LABELS} from '../../components/cueRailData';

interface HistoryPanelProps {
  reviews: ReviewRecord[];
  transitions: StateTransition[];
}

type HistoryItem =
  | {kind: 'review'; at: string; review: ReviewRecord}
  | {kind: 'transition'; at: string; transition: StateTransition};

export function HistoryPanel({reviews, transitions}: HistoryPanelProps) {
  const items: HistoryItem[] = [
    ...reviews.map((review) => ({kind: 'review' as const, at: review.created_at ?? '', review})),
    ...transitions.map((transition) => ({kind: 'transition' as const, at: transition.occurred_at ?? '', transition})),
  ].sort((a, b) => a.at.localeCompare(b.at));
  if (items.length === 0) return <p className="empty-state">尚无审核或状态历史。</p>;
  return (
    <ol className="history-list">
      {items.map((item, index) => (
        <li key={item.kind === 'review' ? item.review.review_id : (item.transition.transition_id ?? `transition-${String(index)}`)}>
          <time dateTime={item.at}>
            {new Intl.DateTimeFormat('zh-CN', {dateStyle: 'short', timeStyle: 'short'}).format(new Date(item.at))}
          </time>
          {item.kind === 'review' ? (
            <div>
              <strong>
                {item.review.stage === 'first' ? '人工初审' : '人工终审'} ·{' '}
                {item.review.decision === 'approve' ? '批准' : '要求修改'}
              </strong>
              <p>{item.review.note ?? '没有附加说明'}</p>
              <span className="metadata">{item.review.reviewer_id} · story v{String(item.review.reviewed_story_version)}</span>
            </div>
          ) : (
            <div>
              <strong>
                {STATUS_LABELS[item.transition.from_status]} → {STATUS_LABELS[item.transition.to_status]}
              </strong>
              <p>{item.transition.reason}</p>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
