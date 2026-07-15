import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, RotateCcw} from 'lucide-react';
import {type ChangeEvent, useRef, useState} from 'react';
import {useForm, useWatch} from 'react-hook-form';

import {listRoles, submitFirstReview} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {FirstReviewSubmission, SpeechEmotion, Story} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {CATEGORY_LABELS} from '../../components/contentCategories';
import {SPEECH_EMOTIONS} from '../../components/narrationOptions';

interface ReviewForm {
  reviewerId: string;
  translation: string;
  summary: string;
  keyPoints: string;
  category: keyof typeof CATEGORY_LABELS;
  candidateRecommendation: boolean;
  style: string;
  duration: number;
  speakerId: string;
  spokenLanguage: string;
  captionLanguage: string;
  speed: number;
  note: string;
}

interface FirstReviewPanelProps {
  story: Story;
}

function resolveEmotion(value: string): SpeechEmotion | null {
  return SPEECH_EMOTIONS.includes(value as SpeechEmotion)
    ? value as SpeechEmotion
    : null;
}

export function FirstReviewPanel({story}: FirstReviewPanelProps) {
  const storyId = story.story_id;
  const queryClient = useQueryClient();
  const retryReviewId = useRef<string | null>(null);
  const [pendingDecision, setPendingDecision] = useState<'approve' | 'request_changes' | null>(null);
  const rolesQuery = useQuery({
    queryKey: queryKeys.roles(true),
    queryFn: () => listRoles(true),
  });
  const {register, getValues, setValue, control, formState} = useForm<ReviewForm>({
    defaultValues: {
      reviewerId: 'local-editor',
      translation: story.translation?.translated_text ?? '',
      summary: story.translation?.summary ?? '',
      keyPoints: story.translation?.key_points?.join('\n') ?? '',
      category: story.translation?.screening.category ?? 'kindness',
      candidateRecommendation: story.translation?.screening.candidate_recommendation ?? false,
      style: story.preferences.style,
      duration: story.preferences.target_duration_seconds,
      speakerId: story.preferences.speaker_id,
      spokenLanguage: story.preferences.spoken_language ?? '',
      captionLanguage: story.preferences.caption_language ?? story.target_language,
      speed: story.preferences.speed,
      note: '',
    },
  });
  const selectedSpeakerId = useWatch({control, name: 'speakerId'});
  const eligibleRoles = (rolesQuery.data ?? []).filter(
    (role) => role.enabled && role.tts_enabled && resolveEmotion(role.default_emotion) !== null,
  );
  const selectedRole = eligibleRoles.find((role) => role.speaker_id === selectedSpeakerId);
  const selectedEmotion = selectedRole === undefined
    ? null
    : resolveEmotion(selectedRole.default_emotion);
  const canApprove = rolesQuery.isSuccess && selectedRole !== undefined && selectedEmotion !== null;

  const mutation = useMutation({
    mutationFn: async ({decision}: {decision: 'approve' | 'request_changes'}) => {
      if (storyId === undefined) throw new Error('Story ID is missing.');
      const values = getValues();
      const role = eligibleRoles.find((item) => item.speaker_id === values.speakerId);
      const emotion = role === undefined ? null : resolveEmotion(role.default_emotion);
      if (decision === 'approve' && (role === undefined || emotion === null || !rolesQuery.isSuccess)) {
        throw new Error('Select an enabled, TTS-capable role before approving the first review.');
      }
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
        preferences: role === undefined || emotion === null ? null : {
          ...story.preferences,
          style: values.style,
          target_duration_seconds: Number(values.duration),
          speaker_id: role.speaker_id,
          spoken_language: values.spokenLanguage.trim() || role.default_spoken_language,
          caption_language: values.captionLanguage.trim(),
          emotion,
          speed: Number(values.speed),
          pitch: story.preferences.pitch,
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
      <p className="review-help">确认事实、译文和关键点。在这里设定脚本参数；批准后只生成口播文本，不会启动本地 TTS。</p>
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
      <fieldset className="field-group wide">
        <legend className="eyebrow">SCRIPT SETTINGS</legend>
        <p className="field-hint">只能选择已启用、已完成本地 TTS 配置的角色；音高沿用故事当前值且不在此处显示。</p>
        <div className="form-grid">
          <label className="field">
            <span>播报角色</span>
            <select
              className="select"
              disabled={rolesQuery.isLoading}
              {...register('speakerId', {
                onChange: (event: ChangeEvent<HTMLSelectElement>) => {
                  const role = eligibleRoles.find((item) => item.speaker_id === event.currentTarget.value);
                  if (role !== undefined) {
                    setValue('speed', role.default_speed, {shouldDirty: true});
                    setValue('spokenLanguage', role.default_spoken_language, {shouldDirty: true});
                  }
                },
              })}
            >
              <option value="" disabled>请选择可合成的播报角色</option>
              {selectedSpeakerId !== '' && selectedRole === undefined ? (
                <option value={selectedSpeakerId} disabled>当前角色不可用于本地 TTS</option>
              ) : null}
              {eligibleRoles.map((role) => (
                <option key={role.profile_id ?? role.slug} value={role.speaker_id}>{role.display_name} · {role.speaker_id}</option>
              ))}
            </select>
            <small>{rolesQuery.isLoading ? '正在加载角色…' : rolesQuery.isSuccess ? '仅显示可立即用于本地 TTS 的角色。' : '角色列表不可用，不能批准初审。'}</small>
          </label>
          <label className="field">
            <span>语速</span>
            <input className="input" type="number" min={0.6} max={1.65} step={0.05} {...register('speed', {valueAsNumber: true})} />
          </label>
          <label className="field">
            <span>口播语言</span>
            <input className="input mono" placeholder={selectedRole?.default_spoken_language ?? 'zh-CN'} {...register('spokenLanguage')} />
          </label>
          <label className="field">
            <span>字幕语言</span>
            <input className="input mono" required placeholder="zh-CN" {...register('captionLanguage')} />
          </label>
        </div>
      </fieldset>
      <div className="form-grid">
        <label className="field">
          <span>播报风格</span>
          <input className="input" required {...register('style')} />
        </label>
        <label className="field">
          <span>目标秒数</span>
          <input className="input" type="number" min={5} max={600} {...register('duration', {valueAsNumber: true})} />
        </label>
      </div>
      <label className="field">
        <span>审核说明</span>
        <textarea className="textarea compact" {...register('note')} />
      </label>
      {rolesQuery.error === null ? null : <ApiErrorNotice error={rolesQuery.error} />}
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
          disabled={mutation.isPending || formState.isSubmitting || !canApprove}
          onClick={() => setPendingDecision('approve')}
        >
          <CheckCircle2 size={18} aria-hidden="true" />
          {mutation.isPending ? '正在生成口播文本…' : '批准并生成口播文本'}
        </button>
      </div>
      {canApprove ? null : (
        <p className="pending-note" role="status">
          {rolesQuery.isLoading
            ? '正在校验可用角色。'
            : '批准前请选择一个已启用且具备完整本地 TTS 配置的角色。'}
        </p>
      )}
      {mutation.isPending ? (
        <p className="pending-note" role="status" aria-live="polite">
          正在生成口播文本。请保持页面打开；中断后可从安全检查点恢复。
        </p>
      ) : null}
      <ConfirmDialog
        open={pendingDecision !== null}
        title={pendingDecision === 'approve' ? '批准初审' : '保存修改'}
        message={
          pendingDecision === 'approve'
            ? '批准后将生成口播文本，随后仍需人工审稿并手动启动语音合成。确认继续？'
            : '保存修改后将更新初审记录，但不会推进到脚本生成阶段。'
        }
        confirmLabel={pendingDecision === 'approve' ? '批准并生成口播文本' : '确认保存'}
        onConfirm={() => {
          if (pendingDecision !== null) mutation.mutate({decision: pendingDecision});
          setPendingDecision(null);
        }}
        onCancel={() => setPendingDecision(null)}
      />
    </form>
  );
}
