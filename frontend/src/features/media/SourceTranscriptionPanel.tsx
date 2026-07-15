import {useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {CheckCircle2, LoaderCircle, Speech, Square, XCircle} from 'lucide-react';

import {
  cancelSourceMediaTranscription,
  listSourceMediaTranscriptions,
  reviewSourceMediaTranscription,
  startSourceMediaTranscription,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {
  SourceMediaArtifact,
  SourceMediaTranscription,
  Story,
  TimedCaptionCue,
} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {useToast} from '../../components/toastContext';

interface SourceTranscriptionPanelProps {
  artifact: SourceMediaArtifact;
  story: Story;
}

const activeStatuses = new Set(['QUEUED', 'PROCESSING']);
const statusLabels: Record<SourceMediaTranscription['status'], string> = {
  QUEUED: '等待本地识别',
  PROCESSING: '正在识别与翻译',
  PENDING_REVIEW: '字幕待人工审核',
  APPROVED: '字幕已批准',
  REJECTED: '字幕已驳回',
  FAILED: '识别失败',
  CANCELLED: '识别已取消',
};

function latest(items: SourceMediaTranscription[]): SourceMediaTranscription | undefined {
  return [...items].sort((left, right) => (
    Date.parse(right.updated_at ?? '') - Date.parse(left.updated_at ?? '')
  ))[0];
}

function formatTime(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(2)}s`;
}

function CaptionReviewEditor({
  artifactId,
  storyId,
  transcription,
}: {
  artifactId: string;
  storyId: string;
  transcription: SourceMediaTranscription;
}) {
  const [cues, setCues] = useState<TimedCaptionCue[]>(transcription.cues ?? []);
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const review = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => reviewSourceMediaTranscription(
      storyId,
      artifactId,
      transcription.transcription_id ?? '',
      {
        decision,
        expected_version: transcription.version,
        reviewer_id: 'story-workbench',
        revised_cues: cues,
      },
    ),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sourceTranscriptions(storyId, artifactId),
      });
      pushToast({
        message: result.status === 'APPROVED' ? '原视频字幕已批准。' : '原视频字幕已驳回。',
        durationMs: 3000,
      });
    },
    onError: (error) => pushToast({
      message: `字幕审核失败：${error instanceof Error ? error.message : '未知错误'}`,
      variant: 'caution',
      durationMs: 5000,
    }),
  });

  const updateCaption = (cueIndex: number, captionIndex: number, text: string) => {
    setCues((current) => current.map((cue, currentCueIndex) => (
      currentCueIndex !== cueIndex ? cue : {
        ...cue,
        captions: cue.captions.map((caption, currentCaptionIndex) => (
          currentCaptionIndex === captionIndex ? {...caption, text} : caption
        )),
      }
    )));
  };

  return (
    <div className="source-transcript-review">
      <p className="metadata">
        可修正文案，但时间戳和片段身份会由后端锁定，不能在审核中改写。
      </p>
      <div className="source-transcript-cues">
        {cues.map((cue, cueIndex) => (
          <fieldset className="source-transcript-cue" key={cue.cue_id ?? cue.sequence}>
            <legend>{formatTime(cue.start_ms)} — {formatTime(cue.end_ms)}</legend>
            {cue.captions.map((caption, captionIndex) => (
              <label className="field" key={`${caption.kind}-${caption.language}`}>
                <span>{caption.kind === 'verbatim' ? '原文' : '翻译'} · {caption.language}</span>
                <textarea
                  className="input textarea"
                  rows={2}
                  value={caption.text}
                  onChange={(event) => updateCaption(cueIndex, captionIndex, event.target.value)}
                />
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      <div className="button-row">
        <button
          className="button"
          type="button"
          disabled={review.isPending}
          onClick={() => review.mutate('approve')}
        >
          <CheckCircle2 size={15} aria-hidden="true" /> 批准字幕
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={review.isPending}
          onClick={() => review.mutate('reject')}
        >
          <XCircle size={15} aria-hidden="true" /> 驳回
        </button>
      </div>
    </div>
  );
}

export function SourceTranscriptionPanel({artifact, story}: SourceTranscriptionPanelProps) {
  const storyId = story.story_id ?? '';
  const artifactId = artifact.artifact_id ?? '';
  const [sourceLanguageHint, setSourceLanguageHint] = useState('');
  const [targetLanguage, setTargetLanguage] = useState(story.target_language);
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const transcriptions = useQuery({
    queryKey: queryKeys.sourceTranscriptions(storyId, artifactId),
    queryFn: () => listSourceMediaTranscriptions(storyId, artifactId),
    enabled: storyId !== '' && artifactId !== '',
    refetchInterval: (query) => (
      (query.state.data ?? []).some((item) => activeStatuses.has(item.status)) ? 1500 : false
    ),
  });
  const current = useMemo(() => latest(transcriptions.data ?? []), [transcriptions.data]);
  const invalidate = () => queryClient.invalidateQueries({
    queryKey: queryKeys.sourceTranscriptions(storyId, artifactId),
  });
  const start = useMutation({
    mutationFn: () => startSourceMediaTranscription(storyId, artifactId, {
      expected_story_version: story.version,
      requested_by: 'story-workbench',
      source_language_hint: sourceLanguageHint.trim() || null,
      target_caption_language: targetLanguage.trim(),
    }),
    onSuccess: () => {
      void invalidate();
      pushToast({message: '原视频识别任务已进入本地队列。', durationMs: 3000});
    },
    onError: (error) => pushToast({
      message: `无法启动字幕识别：${error instanceof Error ? error.message : '未知错误'}`,
      variant: 'caution',
      durationMs: 5000,
    }),
  });
  const cancel = useMutation({
    mutationFn: () => cancelSourceMediaTranscription(
      storyId,
      artifactId,
      current?.transcription_id ?? '',
    ),
    onSuccess: () => void invalidate(),
  });
  const isActive = current !== undefined && activeStatuses.has(current.status);

  return (
    <div className="source-transcription-panel">
      <div className="source-transcription-heading">
        <div>
          <strong><Speech size={15} aria-hidden="true" /> 原视频字幕</strong>
          <p className="metadata">本地 ASR 生成原文时间戳；跨语言字幕由 LLM 翻译后必须人工审核。</p>
        </div>
        {current === undefined ? null : (
          <span className={`badge ${current.status === 'APPROVED' ? 'success' : 'caution'}`}>
            {statusLabels[current.status]}
          </span>
        )}
      </div>
      {transcriptions.error === null ? null : (
        <ApiErrorNotice error={transcriptions.error} onRetry={() => void transcriptions.refetch()} />
      )}
      {current === undefined || ['FAILED', 'CANCELLED', 'REJECTED'].includes(current.status) ? (
        <div className="source-transcription-controls">
          <label className="field">
            <span>原语言提示（可留空自动检测）</span>
            <input
              className="input"
              placeholder="例如 en、ja"
              value={sourceLanguageHint}
              onChange={(event) => setSourceLanguageHint(event.target.value)}
            />
          </label>
          <label className="field">
            <span>字幕目标语言</span>
            <input
              className="input"
              value={targetLanguage}
              onChange={(event) => setTargetLanguage(event.target.value)}
            />
          </label>
          <button
            className="button"
            type="button"
            disabled={start.isPending || targetLanguage.trim() === ''}
            onClick={() => start.mutate()}
          >
            <Speech size={15} aria-hidden="true" /> 生成原视频字幕
          </button>
        </div>
      ) : null}
      {isActive ? (
        <div className="source-transcription-progress">
          <LoaderCircle className="spin" size={16} aria-hidden="true" />
          <span>{statusLabels[current.status]}，第 {current.attempt_count} 次尝试</span>
          <button
            className="button secondary"
            type="button"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            <Square size={13} aria-hidden="true" /> 取消
          </button>
        </div>
      ) : null}
      {current?.status === 'FAILED' && current.failures?.length ? (
        <ApiErrorNotice error={new Error(current.failures.at(-1)?.message ?? '字幕识别失败')} />
      ) : null}
      {current?.detected_language === null || current?.detected_language === undefined ? null : (
        <p className="metadata">
          检测语言 {current.detected_language}
          {current.language_probability === null || current.language_probability === undefined
            ? ''
            : ` · 置信度 ${(current.language_probability * 100).toFixed(1)}%`}
          {' · '}{current.model_identity}
        </p>
      )}
      {current?.status === 'PENDING_REVIEW' ? (
        <CaptionReviewEditor
          key={`${current.transcription_id}-${current.version}`}
          artifactId={artifactId}
          storyId={storyId}
          transcription={current}
        />
      ) : null}
      {current?.status === 'APPROVED' ? (
        <div className="source-transcript-readonly">
          {(current.cues ?? []).map((cue) => (
            <p key={cue.cue_id ?? cue.sequence}>
              <span className="metadata">{formatTime(cue.start_ms)} </span>
              {cue.captions.find((caption) => caption.kind === 'translation')?.text
                ?? cue.captions.find((caption) => caption.kind === 'verbatim')?.text}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
