import {useQuery} from '@tanstack/react-query';
import {ArrowLeft, CheckCircle2, ExternalLink, FileClock, Hash, Languages} from 'lucide-react';
import {useState} from 'react';
import {Link, useParams} from 'react-router-dom';

import {
  getProductionManifest,
  getStory,
  listReviews,
  listTransitions,
} from '../../api/client';
import {queryKeys} from '../../api/queryKeys';
import type {ScriptDocument} from '../../api/types';
import {ApiErrorNotice} from '../../components/ApiErrorNotice';
import {CueRail} from '../../components/CueRail';
import {STATUS_LABELS} from '../../components/cueRailData';
import {ScreeningBadge} from '../../components/ScreeningBadge';
import {AudioPanel} from '../audio/AudioPanel';
import {HistoryPanel} from '../history/HistoryPanel';
import {FirstReviewPanel} from '../reviews/FirstReviewPanel';
import {ResumePanel} from '../reviews/ResumePanel';
import {SecondReviewPanel} from '../reviews/SecondReviewPanel';
import {ScriptEditor} from '../script/ScriptEditor';

export function StoryWorkbenchPage() {
  const {storyId = ''} = useParams();
  const storyQuery = useQuery({
    queryKey: queryKeys.story(storyId),
    queryFn: () => getStory(storyId),
    enabled: storyId !== '',
    refetchInterval: (state) => {
      const status = state.state.data?.status;
      return status === 'PROCESSING_SCRIPT' || status === 'SCRIPT_READY' ? 2_000 : false;
    },
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
  const serverScript = story.script ?? null;
  const scriptDraft = (
    scriptEdit?.storyId === storyId
    && scriptEdit.script.revision === serverScript?.revision
  ) ? scriptEdit.script : serverScript;
  const setScriptDraft = (script: ScriptDocument) => {
    setScriptEdit({storyId, script});
  };
  const sourceIsUrl = story.source.kind === 'url';
  const recoverable = ['FETCHED', 'TRANSLATED', 'PROCESSING_SCRIPT', 'SCRIPT_READY'].includes(story.status)
    || (story.status === 'PENDING_SECOND_REVIEW' && story.audio == null);

  return (
    <div className="page workbench-page">
      <Link className="back-link" to="/stories">
        <ArrowLeft size={17} aria-hidden="true" /> 返回故事队列
      </Link>
      <header className="workbench-header">
        <div>
          <p className="eyebrow">{story.source.fetcher} · {STATUS_LABELS[story.status]}</p>
          <h1>{story.source.title}</h1>
          <div className="header-meta metadata">
            <span><Hash size={14} aria-hidden="true" /> {story.story_id}</span>
            <span>trace {story.trace_id}</span>
            <span>v{String(story.version ?? 1)}</span>
          </div>
        </div>
        {sourceIsUrl ? (
          <a className="button" href={story.source.final_uri} target="_blank" rel="noreferrer">
            查看原始页面 <ExternalLink size={16} aria-hidden="true" />
          </a>
        ) : null}
      </header>
      <CueRail status={story.status} />

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

          {scriptDraft === null ? null : (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <p className="eyebrow">SCRIPT</p>
                  <h2>口播脚本</h2>
                </div>
                <span className="metadata">{String(scriptDraft.segments.length)} 段 · {scriptDraft.language}</span>
              </div>
              <div className="panel-body">
                <ScriptEditor
                  script={scriptDraft}
                  onChange={setScriptDraft}
                  readOnly={story.status !== 'PENDING_SECOND_REVIEW'}
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
                  <p className="eyebrow">MANIFEST 1.0</p>
                  <h2>视频时间轴输入</h2>
                </div>
                <span className="metadata">{manifestQuery.data === undefined ? '读取中' : `${(manifestQuery.data.total_duration_ms / 1000).toFixed(2)}s`}</span>
              </div>
              <div className="panel-body manifest-list">
                {manifestQuery.error === null ? null : <ApiErrorNotice error={manifestQuery.error} />}
                {manifestQuery.data?.timeline.map((item) => (
                  <div key={item.segment_id}>
                    <span className="metadata">{(item.start_ms / 1000).toFixed(2)} → {(item.end_ms / 1000).toFixed(2)}</span>
                    <p>{item.text}</p>
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
          ) : story.status === 'PENDING_SECOND_REVIEW' && story.audio !== null && story.audio !== undefined && scriptDraft !== null ? (
            <SecondReviewPanel story={story} revisedScript={scriptDraft} />
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
    </div>
  );
}
