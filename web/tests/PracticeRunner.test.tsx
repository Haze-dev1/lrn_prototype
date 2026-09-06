/**
 * Practice reveals the grade for each answer immediately — the one way it deliberately differs
 * from the diagnostic. These tests pin that difference and the states around it.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GradePanel } from '@/features/practice/components/GradePanel';
import { PracticeRunner } from '@/features/practice/components/PracticeRunner';
import type { GradedAttempt, SessionQuestion, SessionState } from '@/lib/api/sessions';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));

const submitAnswer = vi.fn();
const fetchAttempt = vi.fn();
const completeSession = vi.fn();
vi.mock('@/lib/api/sessions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sessions')>();
  return {
    ...actual,
    submitAnswer: (...args: unknown[]) => submitAnswer(...args),
    fetchAttempt: (...args: unknown[]) => fetchAttempt(...args),
    completeSession: (...args: unknown[]) => completeSession(...args),
  };
});

function question(index: number, overrides: Partial<SessionQuestion> = {}): SessionQuestion {
  return {
    position: index,
    id: `question-${index}`,
    question_version_id: `version-${index}`,
    category_slug: 'valuation',
    category_name: 'Valuation',
    subcategory: null,
    difficulty: 2,
    prompt: `Prompt number ${index}`,
    attempt_id: null,
    grading_status: null,
    ...overrides,
  };
}

function session(overrides: Partial<SessionState> = {}): SessionState {
  return {
    id: 'session-1',
    type: 'practice',
    status: 'in_progress',
    question_count: 2,
    answered_count: 0,
    started_at: '2026-01-01T00:00:00Z',
    finished_at: null,
    selection_rationale: {
      strategy: 'practice_v1',
      explanation: 'Valuation is currently your weakest category at 54.',
      focus_category: 'valuation',
      requested_category: null,
      review_due_count: 2,
      new_count: 3,
      weak_category_count: 4,
    },
    questions: [question(0), question(1)],
    resumed: false,
    ...overrides,
  };
}

function graded(overrides: Partial<GradedAttempt> = {}): GradedAttempt {
  return {
    id: 'attempt-1',
    session_id: 'session-1',
    question_id: 'question-0',
    grading_status: 'graded',
    submitted_at: '2026-01-01T00:00:00Z',
    retry_count: 0,
    answer: 'Subtract net debt and add back cash.',
    score: 72,
    band: 'developing',
    feedback: 'You covered the net debt bridge but did not address cash equivalents.',
    concepts_hit: ['net_debt'],
    concepts_missed: ['cash'],
    mistake_flags: [],
    graded_at: '2026-01-01T00:01:00Z',
    question_prompt: 'Prompt number 0',
    ideal_answer: 'Subtract net debt: total debt less cash and equivalents.',
    category_slug: 'valuation',
    category_name: 'Valuation',
    concept_labels: { net_debt: 'Net debt adjustment', cash: 'Treatment of cash' },
    flagged: false,
    ...overrides,
  };
}

const ANSWER = 'Subtract net debt from enterprise value and add back cash equivalents.';

function type(value: string) {
  fireEvent.change(screen.getByLabelText('Your answer'), { target: { value } });
}

beforeEach(() => {
  push.mockReset();
  submitAnswer.mockReset().mockResolvedValue({ id: 'attempt-1', grading_status: 'pending' });
  fetchAttempt.mockReset().mockResolvedValue(graded());
  completeSession.mockReset().mockResolvedValue(session({ status: 'completed' }));
});

describe('PracticeRunner', () => {
  it('reveals the grade after submitting, unlike the diagnostic', async () => {
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByText('72')).toBeInTheDocument(), { timeout: 4000 });
    expect(screen.getByText('Developing')).toBeInTheDocument();
  });

  it('shows an honest grading state, not a fake typing animation', async () => {
    fetchAttempt.mockResolvedValue({ id: 'attempt-1', grading_status: 'pending' });
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByText(/being read against the rubric/)).toBeInTheDocument());
  });

  it('shows the concepts behind the score, by their readable names', async () => {
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByText('Net debt adjustment')).toBeInTheDocument(), {
      timeout: 4000,
    });
    expect(screen.getByText('Treatment of cash')).toBeInTheDocument();
    expect(screen.queryByText('net_debt')).not.toBeInTheDocument();
  });

  it('offers the next question once a grade is shown', async () => {
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Next question' })).toBeEnabled(), {
      timeout: 4000,
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));
    expect(screen.getByRole('heading', { name: 'Prompt number 1' })).toBeInTheDocument();
  });

  it('clears the grade when moving to the next question', async () => {
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await waitFor(() => expect(screen.getByText('72')).toBeInTheDocument(), { timeout: 4000 });

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));

    expect(screen.queryByText('72')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your answer')).toHaveValue('');
  });

  it('offers to finish on the last question', async () => {
    render(<PracticeRunner session={session({ questions: [question(0)] })} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(
      () => expect(screen.getByRole('button', { name: 'Finish and see summary' })).toBeInTheDocument(),
      { timeout: 4000 },
    );
  });

  it('routes to the summary after finishing', async () => {
    render(<PracticeRunner session={session({ questions: [question(0)] })} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));
    await waitFor(
      () => expect(screen.getByRole('button', { name: 'Finish and see summary' })).toBeInTheDocument(),
      { timeout: 4000 },
    );

    fireEvent.click(screen.getByRole('button', { name: 'Finish and see summary' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/practice/session-1/summary'));
  });

  it('reports a grading failure without inventing a score', async () => {
    fetchAttempt.mockResolvedValue({ id: 'attempt-1', grading_status: 'failed' });
    render(<PracticeRunner session={session()} />);
    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByText(/could not be graded/)).toBeInTheDocument(), {
      timeout: 4000,
    });
    // No grade at all rather than a zero — asserted against the grade panel's own landmark,
    // because the runner legitimately renders other numbers (the question's position).
    expect(screen.queryByRole('region', { name: 'Your grade' })).not.toBeInTheDocument();
    expect(screen.queryByText('Developing')).not.toBeInTheDocument();
  });
});

describe('GradePanel', () => {
  const labels = { net_debt: 'Net debt adjustment', cash: 'Treatment of cash' };

  it('orders the grade as score, evidence, then coaching', () => {
    render(<GradePanel attempt={graded()} labels={labels} />);
    const text = document.body.textContent ?? '';

    expect(text.indexOf('72')).toBeLessThan(text.indexOf('WHAT YOU GOT RIGHT'));
    expect(text.indexOf('WHAT YOU GOT RIGHT')).toBeLessThan(text.indexOf('WHAT TO IMPROVE'));
  });

  it('says so plainly when nothing was covered', () => {
    render(<GradePanel attempt={graded({ concepts_hit: [] })} labels={labels} />);

    expect(screen.getByText('None of the expected concepts.')).toBeInTheDocument();
  });

  it('says so when everything was covered', () => {
    render(<GradePanel attempt={graded({ concepts_missed: [] })} labels={labels} />);

    expect(screen.getByText('You covered everything expected.')).toBeInTheDocument();
  });

  it('keeps the reference answer collapsed rather than leading with it', () => {
    // The student's own answer and the grade are the point; the model answer is there to consult,
    // not to be the first thing read.
    render(<GradePanel attempt={graded()} labels={labels} />);

    expect(
      screen.getByText('Read reference answer').closest('details'),
    ).not.toHaveAttribute('open');
  });

  it('shows mistake flags when the grade carries them', () => {
    render(
      <GradePanel
        attempt={graded({ mistake_flags: ['sign_error'] })}
        labels={{ ...labels, sign_error: 'Reversed the bridge' }}
      />,
    );

    expect(screen.getByText('Reversed the bridge')).toBeInTheDocument();
  });

  it('falls back to a readable form when a label is missing', () => {
    render(<GradePanel attempt={graded()} labels={{}} />);

    expect(screen.getByText('net debt')).toBeInTheDocument();
  });
});
