import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, Mic2} from 'lucide-react';
import {useRef, useState} from 'react';

import {submitSecondReview} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {ScriptDocument, SecondReviewSubmission, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

interface SecondReviewPanelProps {
  story: Story;
  revisedScript: ScriptDocument;
}

export function SecondReviewPanel({story, revisedScript}: SecondReviewPanelProps) {
  const [reviewerId, setReviewerId] = useState('local-editor');
  const [note, setNote] = useState('');
  const retryReviewId = useRef<string | null>(null);
  const queryClient = useQueryClient();
  const storyId = story.story_id;
  const mutation = useMutation({
    mutationFn: async ({decision}: {decision: 'approve' | 'request_changes'}) => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      retryReviewId.current ??= crypto.randomUUID();
      const body: SecondReviewSubmission = {
        review_id: retryReviewId.current,
        expected_story_version: story.version ?? 1,
        decision,
        reviewer_id: reviewerId,
        note: note || null,
        revised_script: decision === 'request_changes' ? revisedScript : null,
      };
      return submitSecondReview(storyId, body);
    },
    onSuccess: async () => {
      retryReviewId.current = null;
      if (storyId === undefined) return;
      await Promise.all([
        queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)}),
        queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
        queryClient.invalidateQueries({queryKey: queryKeys.reviews(storyId)}),
        queryClient.invalidateQueries({queryKey: queryKeys.transitions(storyId)}),
      ]);
    },
  });
  return (
    <div className="review-form">
      <p className="eyebrow">FINAL REVIEW · v{String(story.version ?? 1)}</p>
      <h2>人工终审</h2>
      <p className="review-help">逐段试听并核对脚本。重新合成会创建新 revision，仍停留在终审门前。</p>
      <label className="field">
        <span>审核人</span>
        <input className="input" value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} />
      </label>
      <label className="field">
        <span>审核说明</span>
        <textarea className="textarea compact" value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
      <div className="review-actions stacked">
        <button className="button secondary" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate({decision: 'request_changes'})}>
          <Mic2 size={17} aria-hidden="true" />
          {mutation.isPending ? '重新合成中…' : '保存脚本并重新合成'}
        </button>
        <button className="button primary" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate({decision: 'approve'})}>
          <CheckCircle2 size={18} aria-hidden="true" /> 终审批准
        </button>
      </div>
      {mutation.isPending ? (
        <p className="pending-note" role="status" aria-live="polite">
          本地语音正在合成。请求不会自动重试，避免重复占用 GPU。
        </p>
      ) : null}
    </div>
  );
}
