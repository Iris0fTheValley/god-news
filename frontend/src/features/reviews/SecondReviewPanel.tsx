import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, Mic2} from 'lucide-react';
import {useRef, useState} from 'react';

import {submitSecondReview} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {ScriptDocument, SecondReviewSubmission, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';

interface SecondReviewPanelProps {
  story: Story;
  revisedScript: ScriptDocument;
}

function hasSameRenderableContent(
  original: ScriptDocument | null,
  revised: ScriptDocument,
): boolean {
  if (original === null) return false;
  if (
    original.title !== revised.title
    || original.language !== revised.language
    || original.segments.length !== revised.segments.length
  ) {
    return false;
  }
  return original.segments.every((segment, index) => {
    const candidate = revised.segments[index];
    return candidate !== undefined
      && segment.segment_id === candidate.segment_id
      && segment.sequence === candidate.sequence
      && segment.text === candidate.text
      && segment.speaker_id === candidate.speaker_id
      && segment.emotion === candidate.emotion
      && segment.scene_transition === candidate.scene_transition
      && segment.speed === candidate.speed
      && segment.pitch === candidate.pitch
      && (segment.visual_hint ?? null) === (candidate.visual_hint ?? null);
  });
}

export function SecondReviewPanel({story, revisedScript}: SecondReviewPanelProps) {
  const [reviewerId, setReviewerId] = useState('local-editor');
  const [note, setNote] = useState('');
  const [pendingDecision, setPendingDecision] = useState<'approve' | 'request_changes' | null>(null);
  const retryReviewId = useRef<string | null>(null);
  const queryClient = useQueryClient();
  const storyId = story.story_id;
  const hasScriptChanges = !hasSameRenderableContent(story.script ?? null, revisedScript);
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
        revised_script: decision === 'request_changes' && hasScriptChanges ? revisedScript : null,
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
      <p className="review-help">逐段试听并核对脚本。只有脚本实际改动才会清除音频并返回脚本审核；仅记录问题会保留当前音频和终审门。</p>
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
        <button className="button secondary" type="button" disabled={mutation.isPending || (!hasScriptChanges && note.trim() === '')} onClick={() => setPendingDecision('request_changes')}>
          <Mic2 size={17} aria-hidden="true" />
          {mutation.isPending ? '正在保存终审意见…' : hasScriptChanges ? '保存脚本并返回审核' : '记录问题，保留音频'}
        </button>
        <button className="button primary" type="button" disabled={mutation.isPending} onClick={() => setPendingDecision('approve')}>
          <CheckCircle2 size={18} aria-hidden="true" /> 终审批准
        </button>
      </div>
      {mutation.isPending ? (
        <p className="pending-note" role="status" aria-live="polite">
          正在保存终审意见。
        </p>
      ) : null}
      <ConfirmDialog
        open={pendingDecision !== null}
        title={pendingDecision === 'approve' ? '终审批准' : hasScriptChanges ? '返回脚本审核' : '记录终审问题'}
        message={
          pendingDecision === 'approve'
            ? '批准后脚本与音频将永久冻结。此操作不可撤销，确认继续？'
            : hasScriptChanges
              ? '保存修改后的脚本，清除当前音频并返回脚本审核。语音合成需要后续人工手动启动。'
              : '仅记录终审问题，不会清除当前音频或重新启动语音合成。'
        }
        confirmLabel={pendingDecision === 'approve' ? '批准并冻结' : hasScriptChanges ? '保存并返回审核' : '记录问题'}
        onConfirm={() => {
          if (pendingDecision !== null) mutation.mutate({decision: pendingDecision});
          setPendingDecision(null);
        }}
        onCancel={() => setPendingDecision(null)}
      />
    </div>
  );
}
