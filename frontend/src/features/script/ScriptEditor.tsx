import {ArrowDown, ArrowUp, Plus, Trash2} from 'lucide-react';

import type {ScriptDocument, ScriptSegment} from '../../api/types';

interface ScriptEditorProps {
  script: ScriptDocument;
  onChange: (script: ScriptDocument) => void;
  readOnly?: boolean;
}

function resequence(segments: ScriptSegment[]): ScriptSegment[] {
  return segments.map((segment, index) => ({...segment, sequence: index}));
}

export function ScriptEditor({script, onChange, readOnly = false}: ScriptEditorProps) {
  const updateSegment = (index: number, patch: Partial<ScriptSegment>) => {
    const segments = script.segments.map((segment, itemIndex) =>
      itemIndex === index ? {...segment, ...patch} : segment,
    );
    onChange({...script, segments});
  };
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= script.segments.length) return;
    const segments = [...script.segments];
    [segments[index], segments[target]] = [segments[target], segments[index]];
    onChange({...script, segments: resequence(segments)});
  };
  const remove = (index: number) => {
    if (script.segments.length <= 1) return;
    onChange({...script, segments: resequence(script.segments.filter((_, item) => item !== index))});
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
    onChange({...script, segments: [...script.segments, segment]});
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
            onChange={(event) => onChange({...script, title: event.target.value})}
          />
        </label>
        <span className="metadata">revision {String(script.revision ?? 1)}</span>
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
