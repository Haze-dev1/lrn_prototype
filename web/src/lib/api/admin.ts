/**
 * Typed API client functions for question bank administration.
 *
 * The types here mirror the backend's two response shapes deliberately. `AdminQuestion` and
 * `QuestionVersionSummary` carry no rubric content, so a component built against them cannot
 * render an ideal answer by accident; only `QuestionVersion`, fetched explicitly for the editor,
 * has the grading fields.
 */

import { apiRequest } from '@/lib/api/client';

export type QuestionStatus = 'draft' | 'active' | 'retired';
export type VersionStatus = 'draft' | 'published' | 'superseded';

export interface ConceptEntry {
  key: string;
  label: string;
}

export interface QuestionVersionSummary {
  id: string;
  version: number;
  status: VersionStatus;
  created_by: string | null;
  created_at: string;
}

export interface AdminQuestion {
  id: string;
  source_key: string | null;
  category_slug: string;
  subcategory: string | null;
  difficulty: number;
  status: QuestionStatus;
  created_at: string;
  updated_at: string;
  published_version: QuestionVersionSummary | null;
  version_count: number;
}

export interface AdminQuestionDetail extends AdminQuestion {
  versions: QuestionVersionSummary[];
}

/** A version including its grading content. Only ever fetched for the admin editor. */
export interface QuestionVersion {
  id: string;
  question_id: string;
  version: number;
  status: VersionStatus;
  prompt: string;
  ideal_answer: string;
  expected_concepts: ConceptEntry[];
  common_mistakes: ConceptEntry[];
  rubric: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
}

export interface QuestionListPage {
  items: AdminQuestion[];
  next_cursor: string | null;
}

export interface RubricValidation {
  is_valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface CategoryCoverage {
  slug: string;
  name: string;
  selectable: number;
  required: number;
  shortfall: number;
}

export interface BankCoverage {
  categories: CategoryCoverage[];
  total_selectable: number;
  diagnostic_ready: boolean;
  counts_by_status: Record<string, number>;
}

export interface QuestionFilters {
  category_slug?: string;
  status?: QuestionStatus;
  difficulty?: number;
  search?: string;
  before?: string;
  limit?: number;
}

/** Build a query string from defined filter values only, so empty filters are omitted. */
function toQuery(filters: QuestionFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '' && value !== null) {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

/** List questions for content management. Never cached: the admin edits what it reads. */
export async function listQuestions(filters: QuestionFilters = {}): Promise<QuestionListPage> {
  return apiRequest<QuestionListPage>(`/v1/admin/questions${toQuery(filters)}`, {
    cache: 'no-store',
  });
}

/** Fetch one question with its full version history. */
export async function fetchQuestion(id: string): Promise<AdminQuestionDetail> {
  return apiRequest<AdminQuestionDetail>(`/v1/admin/questions/${id}`, { cache: 'no-store' });
}

/** Fetch one version including its grading content. */
export async function fetchVersion(
  questionId: string,
  versionId: string,
): Promise<QuestionVersion> {
  return apiRequest<QuestionVersion>(
    `/v1/admin/questions/${questionId}/versions/${versionId}`,
    { cache: 'no-store' },
  );
}

/** Report gradeable question counts per category and diagnostic readiness. */
export async function fetchCoverage(): Promise<BankCoverage> {
  return apiRequest<BankCoverage>('/v1/admin/questions/coverage', { cache: 'no-store' });
}

export interface VersionContentInput {
  prompt: string;
  ideal_answer: string;
  expected_concepts: ConceptEntry[];
  common_mistakes: ConceptEntry[];
  rubric: Record<string, unknown>;
}

/** Create a question, optionally with its first version. */
export async function createQuestion(input: {
  category_slug: string;
  subcategory?: string | null;
  difficulty: number;
  source_key?: string | null;
  initial_version?: (VersionContentInput & { publish: boolean }) | null;
}): Promise<AdminQuestionDetail> {
  return apiRequest<AdminQuestionDetail>('/v1/admin/questions', {
    method: 'POST',
    body: input,
  });
}

/** Update a question's taxonomy. Grading content is changed by creating a version. */
export async function updateQuestion(
  id: string,
  input: { category_slug?: string; subcategory?: string | null; difficulty?: number },
): Promise<AdminQuestionDetail> {
  return apiRequest<AdminQuestionDetail>(`/v1/admin/questions/${id}`, {
    method: 'PATCH',
    body: input,
  });
}

/** Activate or retire a question. */
export async function setQuestionStatus(
  id: string,
  status: QuestionStatus,
): Promise<AdminQuestionDetail> {
  return apiRequest<AdminQuestionDetail>(`/v1/admin/questions/${id}/status`, {
    method: 'PUT',
    body: { status },
  });
}

/** Create a new version of a question's grading content. */
export async function createVersion(
  questionId: string,
  input: VersionContentInput & { publish: boolean },
): Promise<QuestionVersion> {
  return apiRequest<QuestionVersion>(`/v1/admin/questions/${questionId}/versions`, {
    method: 'POST',
    body: input,
  });
}

/** Edit a draft version in place. Rejected by the API for published or superseded versions. */
export async function updateVersion(
  questionId: string,
  versionId: string,
  input: Partial<VersionContentInput>,
): Promise<QuestionVersion> {
  return apiRequest<QuestionVersion>(
    `/v1/admin/questions/${questionId}/versions/${versionId}`,
    { method: 'PATCH', body: input },
  );
}

/** Publish a version, superseding the one it replaces. */
export async function publishVersion(
  questionId: string,
  versionId: string,
): Promise<QuestionVersion> {
  return apiRequest<QuestionVersion>(
    `/v1/admin/questions/${questionId}/versions/${versionId}/publish`,
    { method: 'POST' },
  );
}

/** Check whether a version is complete enough to publish, without publishing it. */
export async function validateVersion(
  questionId: string,
  versionId: string,
): Promise<RubricValidation> {
  return apiRequest<RubricValidation>(
    `/v1/admin/questions/${questionId}/versions/${versionId}/validation`,
    { cache: 'no-store' },
  );
}
