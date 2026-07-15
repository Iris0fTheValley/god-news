import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  ImageOff,
  ImagePlus,
  Link2,
  Plus,
  Redo2,
  Trash2,
  Undo2,
} from 'lucide-react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {useCallback, useEffect, useId, useRef, useState, type ChangeEvent} from 'react';

import {
  deleteSegmentVisualAsset,
  listStoryVisualAssets,
  uploadSegmentVisualAsset,
  visualAssetContentUrl,
} from '../../api/client';
import type {
  RoleProfile,
  SceneTransition,
  ScriptDocument,
  ScriptSegment,
  SpeechEmotion,
} from '../../api/types';
import {queryKeys} from '../../api/queryKeys';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {
  SCENE_TRANSITIONS,
  SCENE_TRANSITION_LABELS,
  SPEECH_EMOTIONS,
  SPEECH_EMOTION_LABELS,
} from '../../components/narrationOptions';

const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

interface ScriptEditorProps {
  script: ScriptDocument;
  onChange: (script: ScriptDocument) => void;
  roles?: RoleProfile[];
  readOnly?: boolean;
  storyId?: string;
  storyVersion?: number;
  /** False while the script itself has unsaved changes or the workflow is immutable. */
  visualAssetsMutable?: boolean;
}

function resequence(segments: ScriptSegment[]): ScriptSegment[] {
  return segments.map((segment, index) => ({...segment, sequence: index}));
}

/** Deep-clone segments for undo history — avoids shared reference mutation. */
function cloneSegments(segments: ScriptSegment[]): ScriptSegment[] {
  return segments.map((segment) => ({
    ...segment,
    segment_id: segment.segment_id ?? crypto.randomUUID(),
    captions: (segment.captions ?? []).map((caption) => ({...caption})),
  }));
}

function withSpokenText(segment: ScriptSegment, spokenText: string): ScriptSegment {
  const captions = (segment.captions ?? []).map((caption) => (
    caption.kind === 'verbatim'
      ? {...caption, language: segment.spoken_language, text: spokenText}
      : caption
  ));
  if (!captions.some((caption) => caption.kind === 'verbatim')) {
    captions.unshift({kind: 'verbatim', language: segment.spoken_language, text: spokenText});
  }
  return {...segment, spoken_text: spokenText, captions};
}

function withSpokenLanguage(segment: ScriptSegment, language: string): ScriptSegment {
  return {
    ...segment,
    spoken_language: language,
    captions: (segment.captions ?? []).map((caption) => (
      caption.kind === 'verbatim' ? {...caption, language} : caption
    )),
  };
}

export function ScriptEditor({
  script,
  onChange,
  roles = [],
  readOnly = false,
  storyId,
  storyVersion,
  visualAssetsMutable = !readOnly,
}: ScriptEditorProps) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const roleOptionsId = useId();
  const [pendingUploadSegmentId, setPendingUploadSegmentId] = useState<string | null>(null);
  const [knownStoryVersion, setKnownStoryVersion] = useState<number | undefined>(storyVersion);

  /* ── Undo/redo history stack ── */
  const [past, setPast] = useState<ScriptSegment[][]>([]);
  const [future, setFuture] = useState<ScriptSegment[][]>([]);
  const skipHistory = useRef(false);

  const visualAssetsQuery = useQuery({
    queryKey: queryKeys.visualAssets(storyId ?? ''),
    queryFn: () => listStoryVisualAssets(storyId ?? ''),
    enabled: storyId !== undefined && storyId !== '',
  });
  const effectiveStoryVersion = visualAssetsQuery.data?.story_version ?? knownStoryVersion;
  const canMutateVisuals = (
    !readOnly
    && visualAssetsMutable
    && storyId !== undefined
    && storyId !== ''
    && effectiveStoryVersion !== undefined
  );

  const refreshVisualContext = useCallback(async () => {
    if (storyId === undefined || storyId === '') return;
    await Promise.all([
      queryClient.invalidateQueries({queryKey: queryKeys.visualAssets(storyId)}),
      queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)}),
      queryClient.invalidateQueries({queryKey: queryKeys.stories()}),
    ]);
  }, [queryClient, storyId]);

  const uploadVisualMutation = useMutation({
    mutationFn: async ({segmentId, file}: {segmentId: string; file: File}) => {
      if (storyId === undefined || effectiveStoryVersion === undefined) {
        throw new Error('Visual asset context is unavailable. Reload this story and try again.');
      }
      return uploadSegmentVisualAsset(storyId, segmentId, {
        expectedStoryVersion: effectiveStoryVersion,
        expectedScriptRevision: script.revision,
        file,
      });
    },
    onSuccess: async (result) => {
      setKnownStoryVersion(result.story_version);
      await refreshVisualContext();
    },
    onSettled: () => setPendingUploadSegmentId(null),
  });

  const deleteVisualMutation = useMutation({
    mutationFn: async (segmentId: string) => {
      if (storyId === undefined || effectiveStoryVersion === undefined) {
        throw new Error('Visual asset context is unavailable. Reload this story and try again.');
      }
      await deleteSegmentVisualAsset(
        storyId,
        segmentId,
        effectiveStoryVersion,
        script.revision,
      );
      return effectiveStoryVersion;
    },
    onSuccess: async (usedStoryVersion) => {
      setKnownStoryVersion(usedStoryVersion + 1);
      await refreshVisualContext();
    },
  });

  const pushHistory = useCallback(() => {
    if (skipHistory.current) {
      skipHistory.current = false;
      return;
    }
    setPast((previous) => [...previous.slice(-49), cloneSegments(script.segments)]);
    setFuture([]);
  }, [script.segments]);

  const undo = useCallback(() => {
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    setPast((items) => items.slice(0, -1));
    setFuture((items) => [...items, cloneSegments(script.segments)]);
    skipHistory.current = true;
    onChange({...script, segments: cloneSegments(previous)});
  }, [past, script, onChange]);

  const redo = useCallback(() => {
    if (future.length === 0) return;
    const next = future[future.length - 1];
    setFuture((items) => items.slice(0, -1));
    setPast((items) => [...items, cloneSegments(script.segments)]);
    skipHistory.current = true;
    onChange({...script, segments: cloneSegments(next)});
  }, [future, script, onChange]);

  useEffect(() => {
    if (readOnly) return;
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'z' && !event.shiftKey) {
        event.preventDefault();
        undo();
      }
      if ((event.ctrlKey || event.metaKey) && event.key === 'z' && event.shiftKey) {
        event.preventDefault();
        redo();
      }
      if ((event.ctrlKey || event.metaKey) && event.key === 'y') {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [readOnly, undo, redo]);

  const updateSegment = (index: number, patch: Partial<ScriptSegment>) => {
    const segments = script.segments.map((segment, itemIndex) => (
      itemIndex === index ? {...segment, ...patch} : segment
    ));
    pushHistory();
    onChange({...script, segments});
  };

  const replaceSegment = (index: number, segment: ScriptSegment) => {
    const segments = script.segments.map((item, itemIndex) => itemIndex === index ? segment : item);
    pushHistory();
    onChange({...script, segments});
  };

  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= script.segments.length) return;
    const segments = [...script.segments];
    [segments[index], segments[target]] = [segments[target], segments[index]];
    pushHistory();
    onChange({...script, segments: resequence(segments)});
  };

  const remove = (index: number) => {
    if (script.segments.length <= 1) return;
    pushHistory();
    onChange({
      ...script,
      segments: resequence(script.segments.filter((_, itemIndex) => itemIndex !== index)),
    });
  };

  const add = () => {
    const template = script.segments.at(-1);
    const segment: ScriptSegment = {
      segment_id: crypto.randomUUID(),
      sequence: script.segments.length,
      spoken_text: '新增旁白段落',
      spoken_language: script.spoken_language,
      captions: [{kind: 'verbatim', language: script.spoken_language, text: '新增旁白段落'}],
      speaker_id: template?.speaker_id ?? 'narrator',
      emotion: template?.emotion ?? 'happiness',
      speed: template?.speed ?? 1,
      pitch: template?.pitch ?? 0,
      visual_hint: null,
      scene_transition: template?.scene_transition ?? 'black',
    };
    pushHistory();
    onChange({...script, segments: [...script.segments, segment]});
  };

  const requestUpload = (segmentId: string) => {
    setPendingUploadSegmentId(segmentId);
    fileInput.current?.click();
  };

  const onFileChosen = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const segmentId = pendingUploadSegmentId;
    event.target.value = '';
    if (file === undefined || segmentId === null) return;
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      setPendingUploadSegmentId(null);
      return;
    }
    uploadVisualMutation.mutate({segmentId, file});
  };

  const segmentAssets = new Map(
    (visualAssetsQuery.data?.segment_assets ?? []).map((binding) => [
      binding.segment_id,
      binding.asset,
    ]),
  );
  const sourceScreenshot = visualAssetsQuery.data?.source_page_screenshot;
  const sourceCandidateUrl = visualAssetsQuery.data?.source_page_url;
  const visualError = visualAssetsQuery.error ?? uploadVisualMutation.error ?? deleteVisualMutation.error;

  return (
    <div className="script-editor">
      <input
        ref={fileInput}
        className="visually-hidden"
        type="file"
        accept="image/png,image/jpeg,image/webp"
        tabIndex={-1}
        onChange={onFileChosen}
      />
      <datalist id={roleOptionsId}>
        {roles.map((role) => (
          <option key={role.profile_id ?? role.slug} value={role.speaker_id}>
            {role.display_name}{role.enabled ? '' : '（已停用）'}
          </option>
        ))}
      </datalist>
      <div className="script-title-row">
        <label className="field">
          <span>脚本标题</span>
          <input
            className="input"
            value={script.title}
            readOnly={readOnly}
            onChange={(event) => {
              pushHistory();
              onChange({...script, title: event.target.value});
            }}
          />
        </label>
        <span className="metadata">revision {String(script.revision ?? 1)}</span>
        {readOnly || (past.length === 0 && future.length === 0) ? null : (
          <div className="undo-bar">
            <button className="icon-button" type="button" onClick={undo} disabled={past.length === 0} aria-label="撤销 Ctrl+Z">
              <Undo2 size={15} aria-hidden="true" />
            </button>
            <button className="icon-button" type="button" onClick={redo} disabled={future.length === 0} aria-label="重做 Ctrl+Shift+Z">
              <Redo2 size={15} aria-hidden="true" />
            </button>
            <span><kbd>Ctrl+Z</kbd> 撤销 · <kbd>Ctrl+Shift+Z</kbd> 重做</span>
          </div>
        )}
      </div>
      {visualError === null ? null : <ApiErrorNotice error={visualError} />}
      <ol className="segment-list">
        {script.segments.map((segment, index) => {
          const segmentId = segment.segment_id;
          const asset = segmentId === undefined ? undefined : segmentAssets.get(segmentId);
          const preview = asset ?? sourceScreenshot;
          const previewAssetId = preview?.asset_id;
          const isUploading = uploadVisualMutation.isPending
            && uploadVisualMutation.variables?.segmentId === segmentId;
          const isDeleting = deleteVisualMutation.isPending
            && deleteVisualMutation.variables === segmentId;
          const canMutateSegmentVisual = canMutateVisuals && segmentId !== undefined;
          return (
            <li key={segment.segment_id ?? `${String(index)}-${segment.spoken_text}`} className="segment-block">
              <div className="segment-identity">
                <span className="segment-number metadata">{String(index + 1).padStart(2, '0')}</span>
                <label className="field">
                  <span>说话人</span>
                  <input
                    className="input"
                    list={roleOptionsId}
                    value={segment.speaker_id}
                    readOnly={readOnly}
                    onChange={(event) => updateSegment(index, {speaker_id: event.target.value})}
                  />
                  {roles.length === 0 ? <small>暂无可检索角色；保留当前 speaker_id。</small> : null}
                </label>
                <label className="field">
                  <span>情绪</span>
                  {readOnly ? (
                    <span className="badge info">{SPEECH_EMOTION_LABELS[segment.emotion]}</span>
                  ) : (
                    <select
                      className="select"
                      value={segment.emotion}
                      onChange={(event) => updateSegment(index, {emotion: event.target.value as SpeechEmotion})}
                    >
                      {SPEECH_EMOTIONS.map((emotion) => (
                        <option key={emotion} value={emotion}>{SPEECH_EMOTION_LABELS[emotion]}</option>
                      ))}
                    </select>
                  )}
                </label>
                <label className="field">
                  <span>过场</span>
                  {readOnly ? (
                    <span className="badge info">{SCENE_TRANSITION_LABELS[segment.scene_transition]}</span>
                  ) : (
                    <select
                      className="select"
                      value={segment.scene_transition}
                      onChange={(event) => updateSegment(index, {
                        scene_transition: event.target.value as SceneTransition,
                      })}
                    >
                      {SCENE_TRANSITIONS.map((transition) => (
                        <option key={transition} value={transition}>
                          {SCENE_TRANSITION_LABELS[transition]}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              </div>
              <label className="field segment-text">
                <span>口播</span>
                <input
                  className="input"
                  aria-label={`第 ${String(index + 1)} 段口播语言`}
                  value={segment.spoken_language}
                  readOnly={readOnly}
                  onChange={(event) => replaceSegment(index, withSpokenLanguage(segment, event.target.value))}
                />
                <textarea
                  className="textarea"
                  value={segment.spoken_text}
                  readOnly={readOnly}
                  onChange={(event) => replaceSegment(index, withSpokenText(segment, event.target.value))}
                />
              </label>
              {(segment.captions ?? []).filter((caption) => caption.kind === 'translation').map((caption) => (
                <label className="field segment-text" key={`${caption.kind}-${caption.language}`}>
                  <span>翻译字幕 · {caption.language}</span>
                  <textarea
                    className="textarea compact"
                    value={caption.text}
                    readOnly={readOnly}
                    onChange={(event) => updateSegment(index, {
                      captions: (segment.captions ?? []).map((item) => item === caption
                        ? {...item, text: event.target.value}
                        : item),
                    })}
                  />
                </label>
              ))}
              <section className="segment-visual" aria-label={`第 ${String(index + 1)} 段画面素材`}>
                <div className="segment-visual-heading">
                  <span>画面 / 图片</span>
                  {asset === undefined && sourceScreenshot !== undefined ? (
                    <span className="badge info">已捕获新闻页截图（默认）</span>
                  ) : asset === undefined ? <span className="metadata">尚未绑定</span> : <span className="badge">段落上传</span>}
                </div>
                {visualAssetsQuery.isLoading ? (
                  <p className="field-hint">正在核对已捕获素材；不会把新闻链接当作截图。</p>
                ) : previewAssetId === undefined ? (
                  <div className="segment-visual-empty">
                    <ImageOff size={18} aria-hidden="true" />
                    <p>尚未捕获新闻页截图，也没有为本段上传画面。</p>
                  </div>
                ) : (
                  <figure className="segment-visual-preview">
                    <img
                      src={visualAssetContentUrl(storyId ?? '', previewAssetId)}
                      alt={asset === undefined ? '已捕获的新闻页截图' : `第 ${String(index + 1)} 段上传画面`}
                    />
                    <figcaption>{asset === undefined ? '新闻页已捕获截图，作为本段默认画面。' : asset.filename}</figcaption>
                  </figure>
                )}
                {sourceCandidateUrl === undefined || sourceCandidateUrl === null ? null : (
                  <a className="metadata segment-source-link" href={sourceCandidateUrl} target="_blank" rel="noreferrer">
                    <Link2 size={13} aria-hidden="true" /> 原始新闻页候选 <ExternalLink size={12} aria-hidden="true" />
                  </a>
                )}
                {readOnly ? null : (
                  <div className="segment-visual-actions">
                    <button
                      className="button secondary"
                      type="button"
                      disabled={!canMutateSegmentVisual || isUploading || isDeleting}
                      title={canMutateSegmentVisual ? undefined : '请先保存脚本修改，并在可编辑审核阶段上传画面。'}
                      onClick={() => {
                        if (segmentId !== undefined) requestUpload(segmentId);
                      }}
                    >
                      <ImagePlus size={16} aria-hidden="true" /> {isUploading ? '正在上传' : asset === undefined ? '上传画面' : '替换画面'}
                    </button>
                    {asset === undefined ? null : (
                      <button
                        className="button ghost danger"
                        type="button"
                        disabled={!canMutateSegmentVisual || isUploading || isDeleting}
                        onClick={() => {
                          if (segmentId !== undefined) deleteVisualMutation.mutate(segmentId);
                        }}
                      >
                        <Trash2 size={15} aria-hidden="true" /> {isDeleting ? '正在移除' : '移除上传画面'}
                      </button>
                    )}
                  </div>
                )}
              </section>
              <div className="segment-footer">
                <label className="inline-field">
                  语速
                  <input
                    type="number"
                    min={0.6}
                    max={1.65}
                    step={0.05}
                    value={segment.speed}
                    readOnly={readOnly}
                    onChange={(event) => updateSegment(index, {speed: Number(event.target.value)})}
                  />
                </label>
                {readOnly ? null : (
                  <div className="segment-actions">
                    <button className="icon-button" type="button" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`上移第 ${String(index + 1)} 段`}>
                      <ArrowUp size={17} aria-hidden="true" />
                    </button>
                    <button className="icon-button" type="button" onClick={() => move(index, 1)} disabled={index === script.segments.length - 1} aria-label={`下移第 ${String(index + 1)} 段`}>
                      <ArrowDown size={17} aria-hidden="true" />
                    </button>
                    <button className="icon-button danger" type="button" onClick={() => remove(index)} disabled={script.segments.length <= 1} aria-label={`删除第 ${String(index + 1)} 段`}>
                      <Trash2 size={17} aria-hidden="true" />
                    </button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {readOnly ? null : (
        <button className="button" type="button" onClick={add}>
          <Plus size={17} aria-hidden="true" /> 添加段落
        </button>
      )}
    </div>
  );
}
