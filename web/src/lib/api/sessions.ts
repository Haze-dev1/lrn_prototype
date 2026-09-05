/**
 * Typed API client functions for diagnostic sessions and attempts.
 *
 * The types mirror the backend's protected shapes deliberately. `SessionQuestion` has nowhere to
 * put an ideal answer or a rubric, and `AttemptState` has nowhere to put a score — so a component
 * built against them cannot render a grade that has not been earned yet.
 */

import { apiRequest } from '@/lib/api/client';

export type GradingStatus = 'pending' | 'grading' | 'graded' | 'failed';
export type SessionStatus = 'in_progress' | 'completed' | 'abandoned';
export type Band = 'strong' | 'developing' | 'needs_work';

export interface SessionQuestion {
  position: number;
  id: string;
  question_version_id: string;
  category_slug: string;
  category_name: string;
  subcategory: string | null;
  difficulty: number;
  prompt: string;
  attempt_id: string | null;
  grading_status: GradingStatus | null;
}

/** Why a session was composed the way it was. Written at selection time, never re-derived. */
export interface SelectionRationale {
  strategy: string;
  explanation: string;
  focus_category: string | null;
  requested_category: string | null;
  review_due_count: number;
  new_count: number;
  weak_category_count: number;
}

export interface SessionState {
  id: string;
  type: 'diagnostic' | 'practice';
  status: SessionStatus;
  question_count: number;
  answered_count: number;
  started_at: string;
  finished_at: string | null;
  selection_rationale: SelectionRationale | null;
  questions: SessionQuestion[];
  resumed: boolean;
}

export const PRACTICE_SET_SIZES = [5, 10, 20] as const;
export type PracticeSetSize = (typeof PRACTICE_SET_SIZES)[number];

/** An attempt that has not finished grading. Carries no score by construction. */
export interface AttemptState {
  id: string;
  session_id: string;
  question_id: string;
  grading_status: GradingStatus;
  submitted_at: string;
  retry_count: number;
  duplicate?: boolean;
}

/** A graded attempt, with the evidence behind the score. */
export interface GradedAttempt extends AttemptState {
  /** The student's own answer. Needed on review, where the score alone is not reviewable. */
  answer: string;
  score: number;
  band: Band;
  feedback: string;
  concepts_hit: string[];
  concepts_missed: string[];
  mistake_flags: string[];
  graded_at: string;
  question_prompt: string;
  ideal_answer: string;
  category_slug: string;
  category_name: string;
  /** Readable names for the keys in this grade only — never the full declared set. */
  concept_labels: Record<string, string>;
  /** Whether the student has already disputed this grade. */
  flagged: boolean;
}

export interface GradingProgress {
  total: number;
  answered: number;
  graded: number;
  failed: number;
  pending: number;
  grading_complete: boolean;
}

export interface CategoryResult {
  slug: string;
  name: string;
  score: number;
  previous_score: number | null;
  evidence_count: number;
  session_scores: number[];
  answered: number;
  missed_concepts: string[];
}

export interface Recommendation {
  action: string;
  category_slug: string;
  category_name: string;
  reason: string;
}

export interface SessionResults {
  session_id: string;
  status: SessionStatus;
  finished_at: string | null;
  progress: GradingProgress;
  categories: CategoryResult[];
  strengths: string[];
  weaknesses: string[];
  recommendation: Recommendation | null;
}

/** Narrow an attempt to its graded form. The score field is the discriminator. */
export function isGraded(attempt: AttemptState | GradedAttempt): attempt is GradedAttempt {
  return (attempt as GradedAttempt).score !== undefined;
}

/**
 * Read the caller's diagnostic without creating one.
 *
 * Separate from `startDiagnostic` on purpose: asking whether a diagnostic exists must not create
 * one, which is what calling the start endpoint to find out would do.
 */
export async function fetchCurrentDiagnostic(): Promise<SessionState | null> {
  return apiRequest<SessionState | null>('/v1/diagnostic', { cache: 'no-store' });
}

/** Start the diagnostic, or resume the one already in progress. Never cached. */
export async function startDiagnostic(): Promise<SessionState> {
  return apiRequest<SessionState>('/v1/diagnostic', { method: 'POST', cache: 'no-store' });
}

/** Compose and start a practice session. Always creates a new set. */
export async function startPractice(input: {
  size: PracticeSetSize;
  category_slug?: string | null;
}): Promise<SessionState> {
  return apiRequest<SessionState>('/v1/practice', { method: 'POST', body: input });
}

/** Read a session with its questions and progress. */
export async function fetchSession(sessionId: string): Promise<SessionState> {
  return apiRequest<SessionState>(`/v1/sessions/${sessionId}`, { cache: 'no-store' });
}

/** Submit an answer. Resubmitting the same question returns the original attempt. */
export async function submitAnswer(
  sessionId: string,
  input: { question_id: string; answer: string; time_taken_seconds?: number },
): Promise<AttemptState> {
  return apiRequest<AttemptState>(`/v1/sessions/${sessionId}/attempts`, {
    method: 'POST',
    body: input,
  });
}

/** Read an attempt, with its grade once grading has finished. */
export async function fetchAttempt(attemptId: string): Promise<AttemptState | GradedAttempt> {
  return apiRequest<AttemptState | GradedAttempt>(`/v1/attempts/${attemptId}`, {
    cache: 'no-store',
  });
}

/** Finish a session. Requires every question to have been answered. */
export async function completeSession(sessionId: string): Promise<SessionState> {
  return apiRequest<SessionState>(`/v1/sessions/${sessionId}/complete`, { method: 'POST' });
}

/** Read a finished session's results. Poll while `progress.grading_complete` is false. */
export async function fetchResults(sessionId: string): Promise<SessionResults> {
  return apiRequest<SessionResults>(`/v1/sessions/${sessionId}/results`, { cache: 'no-store' });
}
