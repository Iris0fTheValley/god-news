import {useMutation, useQueryClient} from '@tanstack/react-query';
import {FileText, Link2, Plus, X} from 'lucide-react';
import {useEffect, useRef, useState} from 'react';
import {useForm, useWatch} from 'react-hook-form';
import {useNavigate} from 'react-router-dom';

import {createStory} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {IngestRequest} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';

interface FormValues {
  kind: 'url' | 'text';
  url: string;
  title: string;
  text: string;
  language: string;
  targetLanguage: string;
  style: string;
  duration: number;
  speakerId: string;
  emotion: string;
  speed: number;
  pitch: number;
}

export function CreateStoryForm() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {register, handleSubmit, control, formState} = useForm<FormValues>({
    defaultValues: {
      kind: 'url',
      url: '',
      title: '',
      text: '',
      language: '',
      targetLanguage: 'zh-CN',
      style: '准确、克制、让人愿意听完的好事播报',
      duration: 90,
      speakerId: 'narrator',
      emotion: 'neutral',
      speed: 1,
      pitch: 0,
    },
  });
  const kind = useWatch({control, name: 'kind'});
  const mutation = useMutation({
    mutationFn: createStory,
    onSuccess: async (story) => {
      await queryClient.invalidateQueries({queryKey: queryKeys.stories()});
      if (story.story_id !== undefined) void navigate(`/stories/${story.story_id}`);
    },
  });

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && dialog !== null && !dialog.open) dialog.showModal();
  }, [open]);

  const close = () => {
    dialogRef.current?.close();
    setOpen(false);
  };

  const submit = handleSubmit((values) => {
    const common = {
      target_language: values.targetLanguage,
      style: values.style,
      target_duration_seconds: Number(values.duration),
      speaker_id: values.speakerId,
      emotion: values.emotion,
      speed: Number(values.speed),
      pitch: Number(values.pitch),
    };
    const request: IngestRequest =
      values.kind === 'url'
        ? {source: {kind: 'url', url: values.url}, ...common}
        : {
            source: {
              kind: 'text',
              title: values.title || '手动文本',
              text: values.text,
              language: values.language || null,
            },
            ...common,
          };
    mutation.mutate(request);
  });

  if (!open) {
    return (
      <button className="button primary" type="button" onClick={() => setOpen(true)}>
        <Plus size={18} aria-hidden="true" /> 新建故事
      </button>
    );
  }

  return (
    <dialog
      ref={dialogRef}
      className="create-drawer"
      aria-labelledby="create-story-heading"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClose={() => setOpen(false)}
    >
      <div className="panel-header">
        <div>
          <p className="eyebrow">INGEST</p>
          <h2 id="create-story-heading">加入一条候选内容</h2>
        </div>
        <button className="icon-button" type="button" onClick={close} aria-label="关闭新建表单">
          <X aria-hidden="true" />
        </button>
      </div>
      <form className="panel-body form-grid" onSubmit={(event) => void submit(event)}>
        <fieldset className="source-kind wide">
          <legend>内容来源</legend>
          <label>
            <input type="radio" value="url" {...register('kind')} />
            <Link2 size={18} aria-hidden="true" /> URL
          </label>
          <label>
            <input type="radio" value="text" {...register('kind')} />
            <FileText size={18} aria-hidden="true" /> 文本
          </label>
        </fieldset>
        {kind === 'url' ? (
          <label className="field wide">
            <span>公开 URL</span>
            <input className="input" type="url" required {...register('url')} />
            <small>系统会执行 URL 安全策略和三层抓取降级。</small>
          </label>
        ) : (
          <>
            <label className="field">
              <span>标题</span>
              <input className="input" required {...register('title')} />
            </label>
            <label className="field">
              <span>原文语言（可选）</span>
              <input className="input" placeholder="en / ru / zh-CN" {...register('language')} />
            </label>
            <label className="field wide">
              <span>正文</span>
              <textarea className="textarea" required minLength={1} {...register('text')} />
            </label>
          </>
        )}
        <label className="field">
          <span>目标语言</span>
          <input className="input" required {...register('targetLanguage')} />
        </label>
        <label className="field">
          <span>目标时长（秒）</span>
          <input className="input" type="number" min={15} max={600} required {...register('duration', {valueAsNumber: true})} />
        </label>
        <label className="field wide">
          <span>播报风格</span>
          <input className="input" required {...register('style')} />
        </label>
        <details className="advanced-fields wide">
          <summary>语音与角色参数</summary>
          <div className="form-grid">
            <label className="field">
              <span>speaker_id</span>
              <input className="input" required {...register('speakerId')} />
            </label>
            <label className="field">
              <span>情绪</span>
              <input className="input" required {...register('emotion')} />
            </label>
            <label className="field">
              <span>语速</span>
              <input className="input" type="number" min={0.6} max={1.65} step={0.05} {...register('speed', {valueAsNumber: true})} />
            </label>
            <label className="field">
              <span>音高</span>
              <input className="input" type="number" min={-12} max={12} step={0.5} {...register('pitch', {valueAsNumber: true})} />
            </label>
          </div>
        </details>
        {mutation.error === null ? null : <ApiErrorNotice error={mutation.error} />}
        <div className="form-actions wide">
          <button className="button" type="button" onClick={close}>
            取消
          </button>
          <button className="button primary" type="submit" disabled={mutation.isPending || formState.isSubmitting}>
            {mutation.isPending ? '抓取与翻译中…' : '创建并进入初审'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
