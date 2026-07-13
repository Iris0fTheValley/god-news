import {useMutation, useQueryClient} from '@tanstack/react-query';
import {Mic2} from 'lucide-react';
import {useState} from 'react';

import {synthesizeStory} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';

export function TtsSynthesisPanel({story}: {story: Story}) {
  const storyId = story.story_id;
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: async () => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      return synthesizeStory(storyId, {expected_story_version: story.version});
    },
    onSuccess: async () => {
      if (storyId === undefined) return;
      await Promise.all([
        queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)}),
        queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
        queryClient.invalidateQueries({queryKey: queryKeys.transitions(storyId)}),
      ]);
    },
  });

  return (
    <div className="review-form">
      <p className="eyebrow">LOCAL TTS · v{String(story.version)}</p>
      <h2>手动合成本地语音</h2>
      <p className="review-help">脚本已批准。此操作会占用本地语音运行时，完成后自动进入终审；失败会回到此处供人工重试。</p>
      {story.last_failure === null || story.last_failure === undefined ? null : (
        <div className="error-banner"><strong>上次失败：</strong>{story.last_failure.message}</div>
      )}
      {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
      <button className="button primary" type="button" disabled={mutation.isPending} onClick={() => setConfirming(true)}>
        <Mic2 size={18} aria-hidden="true" /> {mutation.isPending ? '本地合成中…' : '启动本地 TTS'}
      </button>
      <ConfirmDialog
        open={confirming}
        title="启动本地语音合成"
        message="将按每段的角色与情绪参考素材启动本地 TTS。运行期间请勿重复提交。"
        confirmLabel="启动合成"
        onConfirm={() => { mutation.mutate(); setConfirming(false); }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
