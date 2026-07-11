import {useQuery} from '@tanstack/react-query';
import {Filter} from 'lucide-react';
import {useSearchParams} from 'react-router-dom';

import {getClassificationMetrics, listStories} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {StoryStatus} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {STATUS_LABELS, STORY_STATUSES} from '../../components/cueRailData';
import {CreateStoryForm} from './CreateStoryForm';
import {StoryCard} from './StoryCard';

function isStoryStatus(value: string | null): value is StoryStatus {
  return value !== null && (STORY_STATUSES as readonly string[]).includes(value);
}

export function StoryListPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('status');
  const status = isStoryStatus(requested) ? requested : undefined;
  const query = useQuery({
    queryKey: queryKeys.stories(status),
    queryFn: () => listStories(status),
    refetchInterval: (state) => {
      const items = state.state.data;
      return items?.some((story) => ['PROCESSING_SCRIPT', 'SCRIPT_READY'].includes(story.status))
        ? 2_000
        : false;
    },
  });
  const metricsQuery = useQuery({
    queryKey: queryKeys.classificationMetrics(),
    queryFn: getClassificationMetrics,
  });

  return (
    <div className="page stories-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">TODAY'S RUNDOWN</p>
          <h1>故事队列</h1>
          <p>先看证据，再做决定。高能耗脚本与语音只会在初审批准后启动。</p>
        </div>
        <CreateStoryForm />
      </div>

      <div className="queue-toolbar">
        <label className="filter-control">
          <Filter size={17} aria-hidden="true" />
          <span>状态</span>
          <select
            className="select"
            value={status ?? ''}
            onChange={(event) => {
              const value = event.target.value;
              setParams(value === '' ? {} : {status: value});
            }}
          >
            <option value="">全部状态</option>
            {STORY_STATUSES.map((item) => (
              <option key={item} value={item}>
                {STATUS_LABELS[item]}
              </option>
            ))}
          </select>
        </label>
        <div className="queue-count metadata">
          <span>{query.data === undefined ? '—' : String(query.data.length)} 条</span>
          <span>
            AI 分类接受率{' '}
            {metricsQuery.data?.accuracy == null
              ? '待积累'
              : `${Math.round(metricsQuery.data.accuracy * 100)}% / ${String(metricsQuery.data.reviewed_count)} 次复核`}
          </span>
        </div>
      </div>

      {query.isLoading ? (
        <div className="story-list" aria-label="正在加载故事">
          {[0, 1, 2].map((item) => (
            <div className="story-cue loading-cue" key={item}>
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          ))}
        </div>
      ) : query.error !== null ? (
        <ApiErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data?.length === 0 ? (
        <div className="empty-state">
          <h2>这个筛选下还没有故事</h2>
          <p>新建一条 URL 或文本，系统会把它送到人工初审门前。</p>
        </div>
      ) : (
        <div className="story-list">
          {query.data?.map((story) => (
            <StoryCard key={story.story_id ?? story.trace_id} story={story} />
          ))}
        </div>
      )}
    </div>
  );
}
