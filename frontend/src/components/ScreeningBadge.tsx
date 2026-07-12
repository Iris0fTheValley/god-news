import {ShieldCheck, ShieldQuestion} from 'lucide-react';

import type {EditorialScreening} from '../api/types';
import {CATEGORY_LABELS} from './contentCategories';

export function ScreeningBadge({screening}: {screening: EditorialScreening}) {
  const Icon = screening.candidate_recommendation ? ShieldCheck : ShieldQuestion;
  return (
    <span
      className={screening.candidate_recommendation ? 'screening-badge candidate' : 'screening-badge hold'}
      title={screening.rationale}
    >
      <Icon size={14} aria-hidden="true" />
      {CATEGORY_LABELS[screening.category]}
      <span>{Math.round(screening.confidence * 100)}%</span>
    </span>
  );
}
