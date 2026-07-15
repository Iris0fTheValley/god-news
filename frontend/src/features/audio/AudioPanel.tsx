import {Headphones} from 'lucide-react';

import {audioClipUrl} from '../../api/client';
import type {Story} from '../../api/types';

interface AudioPanelProps {
  story: Story;
}

export function AudioPanel({story}: AudioPanelProps) {
  if (story.audio === null || story.audio === undefined || story.story_id === undefined) {
    return <p className="empty-state">音频尚未生成。</p>;
  }
  const storyId = story.story_id;
  const segments = new Map(story.script?.segments.map((item) => [item.segment_id, item]) ?? []);
  return (
    <div className="audio-list">
      {story.audio.clips.map((clip, index) => {
        const segment = segments.get(clip.segment_id);
        return (
          <article className="audio-row" key={clip.segment_id}>
            <div className="audio-copy">
              <span className="audio-index metadata">
                <Headphones size={16} aria-hidden="true" /> {String(index + 1).padStart(2, '0')}
              </span>
              <p>{segment?.spoken_text ?? '脚本文本不可用'}</p>
              <span className="metadata">
                {(clip.duration_ms / 1000).toFixed(2)}s · {String(clip.sample_rate_hz)}Hz · {String(clip.channels)}ch
              </span>
            </div>
            <audio controls preload="metadata" src={audioClipUrl(storyId, clip.segment_id)}>
              浏览器不支持音频播放。
            </audio>
          </article>
        );
      })}
    </div>
  );
}
