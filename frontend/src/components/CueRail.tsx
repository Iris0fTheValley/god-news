import {Check, Circle} from 'lucide-react';

import type {StoryStatus} from '../api/types';
import {STATUS_LABELS, STORY_STATUSES} from './cueRailData';

interface CueRailProps {
  status: StoryStatus;
  compact?: boolean;
}

export function CueRail({status, compact = false}: CueRailProps) {
  const current = STORY_STATUSES.indexOf(status);
  return (
    <ol className={compact ? 'cue-rail compact' : 'cue-rail'} aria-label="故事制作进度">
      {STORY_STATUSES.map((item, index) => {
        const state = index < current ? 'complete' : index === current ? 'current' : 'future';
        return (
          <li key={item} className={state} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="cue-dot" aria-hidden="true">
              {state === 'complete' ? <Check size={13} /> : <Circle size={10} fill="currentColor" />}
            </span>
            <span>{STATUS_LABELS[item]}</span>
          </li>
        );
      })}
    </ol>
  );
}
