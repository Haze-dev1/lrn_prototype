/**
 * Typed API client functions for review history, grade disputes, and progress.
 *
 * `ReviewItem` carries no answer text and no reference answer, mirroring the backend: a review
 * list is scanned rather than read, and a component built against this type cannot accidentally
 * render an answer the list never fetched.
 */

import { apiRequest } from '@/lib/api/client';
import type { Band } from '@/lib/api/sessions';

export type FlagReason =
  | 'score_too_low'
  | 'score_too_high'
  | 'wrong_concepts'
  | 'unclear_feedback'
  | 'other';

export const FLAG_REASONS: { value: FlagReason; label: string }[] = [
  { value: 'score_too_low', label: 'The score is too low' },
  { value: 'score_too_high', label: 'The score is too high' },
  { value: 'wrong_concepts', label: 'The concepts marked are wrong' },
  { value: 'unclear_feedback', label: 'The feedback is unclear' },
  { value: 'other', label: 'Something else' },
];

export interface ReviewItem {
  id: string;
  question_id: string;
  category_slug: string;
  category_name: string;
  difficulty: number;
  prompt: string;
  score: number;
  band: Band;
  concepts_missed: string[];
  submitted_at: string;
  flagged: boolean;
}

export interface ReviewPage {
  items: ReviewItem[];
  next_cursor: string | null;
}

export interface ReviewFilters {
  category_slug?: string;
  max_score?: number;
  missed_concept?: string;
  flagged_only?: boolean;
  recent_only?: boolean;
  before?: string;
  limit?: number;
}

export interface CategoryProgress {
  slug: string;
  name: string;
  /** Null for a category with no graded evidence. Never render this as a zero. */
  score: number | null;
  previous_score: number | null;
  evidence_count: number;
  last_attempt_at: string | null;
  provisional: boolean;
}

export interface TrendPoint {
  as_of: string;
  scores: Record<string, number>;
  overall: number | null;
}

export interface Progress {
  categories: CategoryProgress[];
  trend: TrendPoint[];
  overall: number | null;
  measured_categories: number;
  total_categories: number;
  total_evidence: number;
  /** Null when history is too thin to say whether the student is improving. */
  movement: number | null;
  weakest: string | null;
  strongest: string | null;
}

export interface FlagResult {
  id: string;
  status: string;
  already_flagged: boolean;
}

/** Build a query string from defined values only, so empty filters are omitted. */
function toQuery(filters: ReviewFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null && value !== false) {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

/** List the caller's graded attempts, filtered. Never cached: it changes as they practise. */
export async function fetchReview(filters: ReviewFilters = {}): Promise<ReviewPage> {
  return apiRequest<ReviewPage>(`/v1/review${toQuery(filters)}`, { cache: 'no-store' });
}

/** Dispute a grade. Raising it twice returns the existing flag rather than stacking. */
export async function flagGrade(
  attemptId: string,
  input: { reason: FlagReason; comment?: string | null },
): Promise<FlagResult> {
  return apiRequest<FlagResult>(`/v1/attempts/${attemptId}/flag`, {
    method: 'POST',
    body: input,
  });
}

/** Read the caller's mastery across every category, with their trend. */
export async function fetchProgress(): Promise<Progress> {
  return apiRequest<Progress>('/v1/progress', { cache: 'no-store' });
}
