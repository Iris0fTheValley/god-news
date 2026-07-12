import {useMutation, useQueryClient} from '@tanstack/react-query';
import {RefreshCw} from 'lucide-react';

import {resumeStory} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

export function ResumePanel({story}: {story: Story}) {
  const queryClient = useQueryClient();
  const storyId = story.story_id;
  const mutation = useMutation({
    mutationFn: async () => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      return resumeStory(storyId);
    },
    onSuccess: async () => {
      if (storyId === undefined) return;
      await Promise.all([
        queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)}),
        queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
      ]);
    },
  });
  return (
    <div className="review-form">
      <p className="eyebrow">RECOVERY</p>
      <h2>恢复检查点</h2>
      <p className="review-help">
        {story.last_failure?.message ?? '当前步骤尚未完成，可从已持久化的安全检查点继续。'}
      </p>
      {story.last_failure === null || story.last_failure === undefined ? null : (
        <code className="failure-code">{story.last_failure.code}</code>
      )}
      {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
      <button className="button primary" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
        <RefreshCw size={18} aria-hidden="true" />
        {mutation.isPending ? '恢复中…' : '恢复生成'}
      </button>
    </div>
  );
}
