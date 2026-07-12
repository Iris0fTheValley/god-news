import {useMutation, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, RotateCcw} from 'lucide-react';
import {useRef, useState} from 'react';
import {useForm} from 'react-hook-form';

import {submitFirstReview} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {FirstReviewSubmission, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {CATEGORY_LABELS} from '../../components/contentCategories';

interface ReviewForm {
  reviewerId: string;
  translation: string;
  summary: string;
  keyPoints: string;
  category: keyof typeof CATEGORY_LABELS;
  candidateRecommendation: boolean;
  style: string;
  duration: number;
  note: string;
}

interface FirstReviewPanelProps {
  story: Story;
}

export function FirstReviewPanel({story}: FirstReviewPanelProps) {
  const storyId = story.story_id;
  const queryClient = useQueryClient();
  const retryReviewId = useRef<string | null>(null);
  const [pendingDecision, setPendingDecision] = useState<'approve' | 'request_changes' | null>(null);
  const {register, getValues, formState} = useForm<ReviewForm>({
    defaultValues: {
      reviewerId: 'local-editor',
      translation: story.translation?.translated_text ?? '',
      summary: story.translation?.summary ?? '',
      keyPoints: story.translation?.key_points?.join('\n') ?? '',
      category: story.translation?.screening.category ?? 'kindness',
      candidateRecommendation: story.translation?.screening.candidate_recommendation ?? false,
      style: story.preferences.style,
      duration: story.preferences.target_duration_seconds,
      note: '',
    },
  });

  const mutation = useMutation({
    mutationFn: async ({decision}: {decision: 'approve' | 'request_changes'}) => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      const values = getValues();
      retryReviewId.current ??= crypto.randomUUID();
      const body: FirstReviewSubmission = {
        review_id: retryReviewId.current,
        expected_story_version: story.version ?? 1,
        decision,
        reviewer_id: values.reviewerId,
        note: values.note || null,
        corrected_translation: values.translation,
        corrected_summary: values.summary,
        corrected_key_points: values.keyPoints
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        corrected_category: values.category,
        corrected_candidate_recommendation: values.candidateRecommendation,
        preferences: {
          ...story.preferences,
          style: values.style,
          target_duration_seconds: Number(values.duration),
        },
      };
      return submitFirstReview(storyId, body);
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
    <form className="review-form" onSubmit={(event) => event.preventDefault()}>
      <p className="eyebrow">FIRST REVIEW · v{String(story.version ?? 1)}</p>
      <h2>人工初审</h2>
      <p className="review-help">确认事实、译文和关键点。批准后才会生成脚本并加载本地语音模型。</p>
      <label className="field">
        <span>审核人</span>
        <input className="input" required {...register('reviewerId')} />
      </label>
      <label className="field">
        <span>译文</span>
        <textarea className="textarea tall" required {...register('translation')} />
      </label>
      <label className="field">
        <span>摘要</span>
        <textarea className="textarea" required {...register('summary')} />
      </label>
      <label className="field">
        <span>关键点（每行一条）</span>
        <textarea className="textarea compact" {...register('keyPoints')} />
      </label>
      <div className="form-grid">
        <label className="field">
          <span>人工确认分类</span>
          <select className="select" {...register('category')}>
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label className="checkbox-field">
          <input type="checkbox" {...register('candidateRecommendation')} />
          <span>可以进入候选池</span>
        </label>
      </div>
      <div className="form-grid">
        <label className="field">
          <span>播报风格</span>
          <input className="input" required {...register('style')} />
        </label>
        <label className="field">
          <span>目标秒数</span>
          <input className="input" type="number" min={15} max={600} {...register('duration', {valueAsNumber: true})} />
        </label>
      </div>
      <label className="field">
        <span>审核说明</span>
        <textarea className="textarea compact" {...register('note')} />
      </label>
      {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
      <div className="review-actions">
        <button
          className="button secondary"
          type="button"
          disabled={mutation.isPending || formState.isSubmitting}
          onClick={() => setPendingDecision('request_changes')}
        >
          <RotateCcw size={17} aria-hidden="true" /> 保存修改，暂不生成
        </button>
        <button
          className="button primary"
          type="button"
          disabled={mutation.isPending || formState.isSubmitting}
          onClick={() => setPendingDecision('approve')}
        >
          <CheckCircle2 size={18} aria-hidden="true" />
          {mutation.isPending ? '正在生成脚本与音频…' : '批准并生成音频'}
        </button>
      </div>
      {mutation.isPending ? (
        <p className="pending-note" role="status" aria-live="polite">
          首次模型加载约需一分钟。请保持页面打开；中断后可用“恢复生成”继续。
        </p>
      ) : null}
      <ConfirmDialog
        open={pendingDecision !== null}
        title={pendingDecision === 'approve' ? '批准初审' : '保存修改'}
        message={
          pendingDecision === 'approve'
            ? '批准后将触发脚本生成 + 语音合成（约 1 分钟）。此操作不可撤销，确认继续？'
            : '保存修改后将更新初审记录，但不会推进到脚本生成阶段。'
        }
        confirmLabel={pendingDecision === 'approve' ? '批准并生成音频' : '确认保存'}
        onConfirm={() => {
          if (pendingDecision !== null) mutation.mutate({decision: pendingDecision});
          setPendingDecision(null);
        }}
        onCancel={() => setPendingDecision(null)}
      />
    </form>
  );
}
