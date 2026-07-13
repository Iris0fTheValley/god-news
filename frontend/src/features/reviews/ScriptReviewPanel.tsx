import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, FilePenLine} from 'lucide-react';
import {useRef, useState} from 'react';

import {submitScriptReview} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {ScriptDocument, ScriptReviewSubmission, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';

interface ScriptReviewPanelProps {
  story: Story;
  revisedScript: ScriptDocument;
  hasUnsavedChanges: boolean;
}

export function ScriptReviewPanel({story, revisedScript, hasUnsavedChanges}: ScriptReviewPanelProps) {
  const storyId = story.story_id;
  const queryClient = useQueryClient();
  const retryReviewId = useRef<string | null>(null);
  const [reviewerId, setReviewerId] = useState('local-editor');
  const [note, setNote] = useState('');
  const [pendingDecision, setPendingDecision] = useState<'approve' | 'request_changes' | null>(null);

  const mutation = useMutation({
    mutationFn: async ({decision}: {decision: 'approve' | 'request_changes'}) => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      retryReviewId.current ??= crypto.randomUUID();
      const body: ScriptReviewSubmission = {
        review_id: retryReviewId.current,
        expected_story_version: story.version,
        decision,
        reviewer_id: reviewerId,
        note: note.trim() || null,
        revised_script: decision === 'request_changes' && hasUnsavedChanges ? revisedScript : null,
      };
      return submitScriptReview(storyId, body);
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

  const canSaveChanges = hasUnsavedChanges || note.trim() !== '';

  return (
    <div className="review-form">
      <p className="eyebrow">SCRIPT REVIEW · v{String(story.version)}</p>
      <h2>人工审口播文本</h2>
      <p className="review-help">逐段核对角色、情绪和语速。保存修订后仍停留在这个审核门；批准后才可以手动启动本地 TTS。</p>
      <label className="field">
        <span>审核人</span>
        <input className="input" value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} />
      </label>
      <label className="field">
        <span>审核说明</span>
        <textarea className="textarea compact" value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      {hasUnsavedChanges ? <p className="pending-note">脚本有未保存的修订。请先保存修订，再批准脚本。</p> : null}
      {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
      <div className="review-actions stacked">
        <button
          className="button secondary"
          type="button"
          disabled={mutation.isPending || !canSaveChanges}
          onClick={() => setPendingDecision('request_changes')}
        >
          <FilePenLine size={17} aria-hidden="true" /> 保存修订，继续审稿
        </button>
        <button
          className="button primary"
          type="button"
          disabled={mutation.isPending || hasUnsavedChanges}
          onClick={() => setPendingDecision('approve')}
        >
          <CheckCircle2 size={18} aria-hidden="true" /> 批准脚本
        </button>
      </div>
      <ConfirmDialog
        open={pendingDecision !== null}
        title={pendingDecision === 'approve' ? '批准口播脚本' : '保存脚本修订'}
        message={
          pendingDecision === 'approve'
            ? '脚本批准后将等待人工手动启动本地语音合成。'
            : '这会保存当前脚本版本，但不会启动语音合成。'
        }
        confirmLabel={pendingDecision === 'approve' ? '批准脚本' : '保存修订'}
        onConfirm={() => {
          if (pendingDecision !== null) mutation.mutate({decision: pendingDecision});
          setPendingDecision(null);
        }}
        onCancel={() => setPendingDecision(null)}
      />
    </div>
  );
}
