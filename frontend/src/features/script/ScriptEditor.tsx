import {ArrowDown, ArrowUp, Plus, Redo2, Trash2, Undo2} from 'lucide-react';
import {useCallback, useEffect, useRef, useState} from 'react';

import type {ScriptDocument, ScriptSegment} from '../../api/types';

interface ScriptEditorProps {
  script: ScriptDocument;
  onChange: (script: ScriptDocument) => void;
  readOnly?: boolean;
}

function resequence(segments: ScriptSegment[]): ScriptSegment[] {
  return segments.map((segment, index) => ({...segment, sequence: index}));
}

/** Deep-clone segments for undo history — avoids shared reference mutation. */
function cloneSegments(segments: ScriptSegment[]): ScriptSegment[] {
  return segments.map((s) => ({...s, segment_id: s.segment_id ?? crypto.randomUUID()}));
}

export function ScriptEditor({script, onChange, readOnly = false}: ScriptEditorProps) {
  /* ── Undo/redo history stack ── */
  const [past, setPast] = useState<ScriptSegment[][]>([]);
  const [future, setFuture] = useState<ScriptSegment[][]>([]);
  const skipHistory = useRef(false);

  const pushHistory = useCallback(() => {
    if (skipHistory.current) {
      skipHistory.current = false;
      return;
    }
    setPast((prev) => [...prev.slice(-49), cloneSegments(script.segments)]);
    setFuture([]);
  }, [script.segments]);

  const undo = useCallback(() => {
    if (past.length === 0) return;
    const prev = past[past.length - 1];
    setPast((p) => p.slice(0, -1));
    setFuture((f) => [...f, cloneSegments(script.segments)]);
    skipHistory.current = true;
    onChange({...script, segments: cloneSegments(prev)});
  }, [past, script, onChange]);

  const redo = useCallback(() => {
    if (future.length === 0) return;
    const next = future[future.length - 1];
    setFuture((f) => f.slice(0, -1));
    setPast((p) => [...p, cloneSegments(script.segments)]);
    skipHistory.current = true;
    onChange({...script, segments: cloneSegments(next)});
  }, [future, script, onChange]);

  useEffect(() => {
    if (readOnly) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && e.shiftKey) {
        e.preventDefault();
        redo();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [readOnly, undo, redo]);

  /* ── Original functional code (unchanged) ── */
  const updateSegment = (index: number, patch: Partial<ScriptSegment>) => {
    const segments = script.segments.map((segment, itemIndex) =>
      itemIndex === index ? {...segment, ...patch} : segment,
    );
    pushHistory();
    onChange({...script, segments});
  };
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= script.segments.length) return;
    const segments = [...script.segments];
    [segments[index], segments[target]] = [segments[target], segments[index]];
    const resequenced = resequence(segments);
    pushHistory();
    onChange({...script, segments: resequenced});
  };
  const remove = (index: number) => {
    if (script.segments.length <= 1) return;
    const resequenced = resequence(script.segments.filter((_, item) => item !== index));
    pushHistory();
    onChange({...script, segments: resequenced});
  };
  const add = () => {
    const template = script.segments.at(-1);
    const segment: ScriptSegment = {
      segment_id: crypto.randomUUID(),
      sequence: script.segments.length,
      text: '新增旁白段落',
      speaker_id: template?.speaker_id ?? 'narrator',
      emotion: template?.emotion ?? 'neutral',
      speed: template?.speed ?? 1,
      pitch: template?.pitch ?? 0,
      visual_hint: null,
    };
    const next = [...script.segments, segment];
    pushHistory();
    onChange({...script, segments: next});
  };

  return (
    <div className="script-editor">
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
        {readOnly ? null : (past.length > 0 || future.length > 0) ? (
          <div className="undo-bar">
            <button className="icon-button" type="button" onClick={undo} disabled={past.length === 0} aria-label="撤销 Ctrl+Z">
              <Undo2 size={15} aria-hidden="true" />
            </button>
            <button className="icon-button" type="button" onClick={redo} disabled={future.length === 0} aria-label="重做 Ctrl+Shift+Z">
              <Redo2 size={15} aria-hidden="true" />
            </button>
            <span>
              <kbd>Ctrl+Z</kbd> 撤销 · <kbd>Ctrl+Shift+Z</kbd> 重做
            </span>
          </div>
        ) : null}
      </div>
      <ol className="segment-list">
        {script.segments.map((segment, index) => (
          <li key={segment.segment_id ?? `${String(index)}-${segment.text}`} className="segment-block">
            <div className="segment-identity">
              <span className="segment-number metadata">{String(index + 1).padStart(2, '0')}</span>
              <label className="field">
                <span>说话人</span>
                <input
                  className="input"
                  value={segment.speaker_id}
                  readOnly={readOnly}
                  onChange={(event) => updateSegment(index, {speaker_id: event.target.value})}
                />
              </label>
              <label className="field">
                <span>情绪</span>
                <input
                  className="input"
                  value={segment.emotion}
                  readOnly={readOnly}
                  onChange={(event) => updateSegment(index, {emotion: event.target.value})}
                />
              </label>
            </div>
            <label className="field segment-text">
              <span>口播</span>
              <textarea
                className="textarea"
                value={segment.text}
                readOnly={readOnly}
                onChange={(event) => updateSegment(index, {text: event.target.value})}
              />
            </label>
            <label className="field">
              <span>画面提示</span>
              <input
                className="input"
                value={segment.visual_hint ?? ''}
                readOnly={readOnly}
                onChange={(event) => updateSegment(index, {visual_hint: event.target.value || null})}
              />
            </label>
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
        ))}
      </ol>
      {readOnly ? null : (
        <button className="button" type="button" onClick={add}>
          <Plus size={17} aria-hidden="true" /> 添加段落
        </button>
      )}
    </div>
  );
}
