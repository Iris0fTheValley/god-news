import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {ArrowLeft, CheckCircle2, ExternalLink, FileClock, Hash, Languages, RotateCcw, Trash2} from 'lucide-react';
import {useState} from 'react';
import {Link, useNavigate, useParams} from 'react-router-dom';

import {
  deleteStory,
  getProductionManifest,
  getStory,
  listRoles,
  listReviews,
  listTransitions,
  reopenStory,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {ScriptDocument, StateTransition} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {CueRail} from '../../components/CueRail';
import {STATUS_LABELS} from '../../components/cueRailData';
import {ScreeningBadge} from '../../components/ScreeningBadge';
import {useToast} from '../../components/toastContext';
import {AudioPanel} from '../audio/AudioPanel';
import {HistoryPanel} from '../history/HistoryPanel';
import {SourceMediaPanel} from '../media/SourceMediaPanel';
import {FirstReviewPanel} from '../reviews/FirstReviewPanel';
import {ResumePanel} from '../reviews/ResumePanel';
import {ScriptReviewPanel} from '../reviews/ScriptReviewPanel';
import {SecondReviewPanel} from '../reviews/SecondReviewPanel';
import {TtsSynthesisPanel} from '../reviews/TtsSynthesisPanel';
import {ScriptEditor} from '../script/ScriptEditor';

export function StoryWorkbenchPage() {
  const {storyId = ''} = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {push: pushToast} = useToast();
  const [showReopenConfirm, setShowReopenConfirm] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const storyQuery = useQuery({
    queryKey: queryKeys.story(storyId),
    queryFn: () => getStory(storyId),
    enabled: storyId !== '',
    refetchInterval: (state) => {
      const status = state.state.data?.status;
      return status === 'PROCESSING_SCRIPT' || status === 'PROCESSING_TTS' ? 2_000 : false;
    },
  });
  const rolesQuery = useQuery({
    queryKey: queryKeys.roles(),
    queryFn: () => listRoles(),
    enabled: storyQuery.data?.script !== null && storyQuery.data?.script !== undefined,
  });
  const reviewQuery = useQuery({
    queryKey: queryKeys.reviews(storyId),
    queryFn: () => listReviews(storyId),
    enabled: storyId !== '',
  });
  const transitionQuery = useQuery({
    queryKey: queryKeys.transitions(storyId),
    queryFn: () => listTransitions(storyId),
    enabled: storyId !== '',
  });
  const manifestQuery = useQuery({
    queryKey: queryKeys.manifest(storyId),
    queryFn: () => getProductionManifest(storyId),
    enabled: storyQuery.data?.status === 'DONE',
  });
  const [scriptEdit, setScriptEdit] = useState<{
    storyId: string;
    script: ScriptDocument;
  } | null>(null);

  const reopenMutation = useMutation({
    mutationFn: reopenStory,
    onSettled: () => setShowReopenConfirm(false),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)});
      pushToast({message: '故事已重开审核。', durationMs: 3000});
    },
    onError: (err) => {
      pushToast({message: `重开失败：${err instanceof Error ? err.message : '未知错误'}`, variant: 'caution', durationMs: 5000});
    },
  });
  const deleteStoryMutation = useMutation({
    mutationFn: deleteStory,
    onSettled: () => setShowDeleteConfirm(false),
    onSuccess: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.story(storyId)});
      void queryClient.invalidateQueries({queryKey: queryKeys.stories()});
      void navigate('/stories');
      pushToast({message: '故事已归档。', durationMs: 3000});
    },
    onError: (err) => {
      pushToast({message: `归档失败：${err instanceof Error ? err.message : '未知错误'}`, variant: 'caution', durationMs: 5000});
    },
  });

  if (storyQuery.isLoading) {
    return <div className="page loading-state" role="status">正在读取故事工作台…</div>;
  }
  if (storyQuery.error !== null || storyQuery.data === undefined) {
    return (
      <div className="page">
        <ApiErrorNotice error={storyQuery.error ?? new Error('故事响应为空。')} onRetry={() => void storyQuery.refetch()} />
      </div>
    );
  }
  const story = storyQuery.data;
  const displayTitle = story.title ?? story.source.title;
  const serverScript = story.script ?? null;
  const scriptDraft = (
    scriptEdit?.storyId === storyId
    && scriptEdit.script.revision === serverScript?.revision
  ) ? scriptEdit.script : serverScript;
  const setScriptDraft = (script: ScriptDocument) => {
    setScriptEdit({storyId, script});
  };
  const sourceIsUrl = story.source.kind === 'url';
  const isArchived = story.status === 'ARCHIVED';
  const recoverable = ['FETCHED', 'TRANSLATED', 'PROCESSING_SCRIPT', 'PROCESSING_TTS'].includes(story.status);
  const scriptCanBeEdited = story.status === 'SCRIPT_READY' || story.status === 'PENDING_SECOND_REVIEW';
  const hasUnsavedScriptChanges = serverScript !== null
    && scriptDraft !== null
    && JSON.stringify(serverScript) !== JSON.stringify(scriptDraft);

  return (
    <div className="page workbench-page">
      <Link className="back-link" to="/stories">
        <ArrowLeft size={17} aria-hidden="true" /> 返回故事队列
      </Link>
      <header className="workbench-header">
        <div>
          <p className="eyebrow">{story.source.fetcher} · {STATUS_LABELS[story.status]}</p>
          <h1>{displayTitle}</h1>
          <div className="header-meta metadata">
            <span><Hash size={14} aria-hidden="true" /> {story.story_id}</span>
            <span>trace {story.trace_id}</span>
            <span>v{String(story.version ?? 1)}</span>
          </div>
        </div>
        {sourceIsUrl ? (
          <div className="header-actions">
            <a className="button" href={story.source.final_uri} target="_blank" rel="noreferrer">
              查看原始页面 <ExternalLink size={16} aria-hidden="true" />
            </a>
            {story.status === 'DONE' ? (
              <button className="button secondary" type="button" onClick={() => setShowReopenConfirm(true)}>
                <RotateCcw size={16} aria-hidden="true" /> 重开审核
              </button>
            ) : null}
            {isArchived ? null : (
              <button className="icon-button danger" type="button" onClick={() => setShowDeleteConfirm(true)} aria-label="归档故事">
                <Trash2 size={17} aria-hidden="true" />
              </button>
            )}
          </div>
        ) : (
          <div className="header-actions">
            {story.status === 'DONE' ? (
              <button className="button secondary" type="button" onClick={() => setShowReopenConfirm(true)}>
                <RotateCcw size={16} aria-hidden="true" /> 重开审核
              </button>
            ) : null}
            {isArchived ? null : (
              <button className="icon-button danger" type="button" onClick={() => setShowDeleteConfirm(true)} aria-label="归档故事">
                <Trash2 size={17} aria-hidden="true" />
              </button>
            )}
          </div>
        )}
      </header>
      <CueRail status={story.status} />

      {(transitionQuery.data ?? []).length > 0 ? (
        <details className="panel audit-timeline" open={(transitionQuery.data ?? []).length <= 5}>
          <summary className="panel-header" style={{cursor: 'pointer'}}>
            <div>
              <p className="eyebrow">TRANSITION LOG</p>
              <h2>状态迁移记录</h2>
            </div>
            <span className="metadata">{(transitionQuery.data ?? []).length} 步</span>
          </summary>
          <ol className="transition-timeline">
            {(transitionQuery.data ?? []).map((transition: StateTransition, index: number) => {
              const fromLabel = STATUS_LABELS[transition.from_status];
              const toLabel = STATUS_LABELS[transition.to_status];
              const occurredAt = transition.occurred_at ?? '';
              return (
                <li key={transition.transition_id ?? `t-${String(index)}`}>
                  <time dateTime={occurredAt} className="metadata">
                    {occurredAt ? new Intl.DateTimeFormat('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date(occurredAt)) : '—'}
                  </time>
                  <span className="transition-badge from">{fromLabel}</span>
                  <span className="transition-arrow" aria-hidden="true">→</span>
                  <span className="transition-badge to">{toLabel}</span>
                  <span className="metadata transition-reason">{transition.reason}</span>
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}

      <div className="workbench-grid">
        <div className="workbench-content">
          <section className="panel evidence-panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">SOURCE EVIDENCE</p>
                <h2>源信息与翻译</h2>
              </div>
              <span className="metadata"><Languages size={15} aria-hidden="true" /> {story.source.detected_language ?? 'und'} → {story.target_language}</span>
            </div>
            <div className="evidence-split">
              <article>
                <h3>原文</h3>
                <p className="long-copy">{story.original_text}</p>
              </article>
              <article>
                <h3>译文</h3>
                <p className="long-copy">{story.translation?.translated_text ?? '翻译尚未完成。'}</p>
                <h3>摘要</h3>
                <p>{story.translation?.summary ?? '摘要尚未生成。'}</p>
                {story.translation?.screening === undefined ? null : (
                  <div className="screening-detail">
                    <ScreeningBadge screening={story.translation.screening} />
                    <p>{story.translation.screening.rationale}</p>
                    {(story.translation.screening.risk_flags ?? []).length === 0 ? null : (
                      <p className="metadata">
                        风险提示：{(story.translation.screening.risk_flags ?? []).join(' · ')}
                      </p>
                    )}
                  </div>
                )}
                <h3>关键点</h3>
                <ul className="key-points">
                  {story.translation?.key_points?.map((point) => <li key={point}>{point}</li>) ?? null}
                </ul>
              </article>
            </div>
          </section>

          <SourceMediaPanel story={story} />

          {scriptDraft === null ? null : (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">SCRIPT</p>
                  <h2>口播脚本</h2>
                </div>
                <span className="metadata">{String(scriptDraft.segments.length)} 段 · {scriptDraft.spoken_language}</span>
              </div>
              <div className="panel-body">
                <ScriptEditor
                  script={scriptDraft}
                  onChange={setScriptDraft}
                  roles={rolesQuery.data ?? []}
                  readOnly={!scriptCanBeEdited}
                  storyId={story.story_id}
                  storyVersion={story.version}
                  visualAssetsMutable={scriptCanBeEdited && !hasUnsavedScriptChanges}
                />
              </div>
            </section>
          )}

          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">AUDIO</p>
                <h2>本地语音</h2>
              </div>
              <span className="metadata">{story.audio?.model_identity ?? '尚未生成'}</span>
            </div>
            <div className="panel-body"><AudioPanel story={story} /></div>
          </section>

          {story.status !== 'DONE' ? null : (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">MANIFEST 2.0</p>
                  <h2>视频时间轴输入</h2>
                </div>
                <span className="metadata">{manifestQuery.data === undefined ? '读取中' : `${(manifestQuery.data.total_duration_ms / 1000).toFixed(2)}s`}</span>
              </div>
              <div className="panel-body manifest-list">
                {manifestQuery.error === null ? null : <ApiErrorNotice error={manifestQuery.error} />}
                {manifestQuery.data?.timeline.map((item) => (
                  <div key={item.segment_id}>
                    <span className="metadata">{(item.start_ms / 1000).toFixed(2)} → {(item.end_ms / 1000).toFixed(2)}</span>
                    <p>{(item.captions ?? []).find((caption) => caption.kind === 'translation')?.text ?? item.spoken_text}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">AUDIT TRAIL</p>
                <h2>审核与状态历史</h2>
              </div>
              <FileClock size={18} aria-hidden="true" />
            </div>
            <div className="panel-body">
              <HistoryPanel reviews={reviewQuery.data ?? []} transitions={transitionQuery.data ?? []} />
            </div>
          </section>
        </div>

        <aside className="action-inspector" aria-label="当前审核操作">
          {story.status === 'PENDING_FIRST_REVIEW' ? (
            <FirstReviewPanel story={story} />
          ) : story.status === 'SCRIPT_READY' && scriptDraft !== null ? (
            <ScriptReviewPanel
              story={story}
              revisedScript={scriptDraft}
              hasUnsavedChanges={hasUnsavedScriptChanges}
            />
          ) : story.status === 'PENDING_TTS' ? (
            <TtsSynthesisPanel story={story} />
          ) : story.status === 'PENDING_SECOND_REVIEW' && story.audio !== null && story.audio !== undefined && scriptDraft !== null ? (
            <SecondReviewPanel story={story} revisedScript={scriptDraft} />
          ) : story.status === 'ARCHIVED' ? (
            <div className="done-panel">
              <FileClock size={32} aria-hidden="true" />
              <p className="eyebrow">ARCHIVED</p>
              <h2>故事已归档</h2>
              <p>来源证据、版本和审核记录仍可查阅，但此故事不会继续进入制作管线。</p>
            </div>
          ) : story.status === 'DONE' ? (
            <div className="done-panel">
              <CheckCircle2 size={32} aria-hidden="true" />
              <p className="eyebrow">DONE</p>
              <h2>两阶段审核已完成</h2>
              <p>脚本、音频与 manifest 已冻结为当前批准版本。</p>
            </div>
          ) : recoverable ? (
            <ResumePanel story={story} />
          ) : (
            <div className="review-form">
              <p className="eyebrow">IN PROGRESS</p>
              <h2>{STATUS_LABELS[story.status]}</h2>
              <p role="status" aria-live="polite">系统正在推进当前步骤。页面会自动刷新。</p>
            </div>
          )}
        </aside>
      </div>
      <ConfirmDialog
        open={showReopenConfirm}
        title="重开审核"
        message="将把此故事从 DONE 状态回退到终审门前（PENDING_SECOND_REVIEW），允许重新编辑脚本并重新进行终审。"
        confirmLabel="确认重开"
        onConfirm={() => reopenMutation.mutate(storyId)}
        onCancel={() => setShowReopenConfirm(false)}
      />
      <ConfirmDialog
        open={showDeleteConfirm}
        title="归档故事"
        message="归档会保留来源证据和审计记录，并从默认活跃列表中隐藏。"
        variant="danger"
        confirmLabel="确认归档"
        onConfirm={() => deleteStoryMutation.mutate(storyId)}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}
