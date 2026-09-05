/**
 * The assessment surface.
 *
 * The claims under test are product decisions, not styling: the diagnostic never reveals a grade
 * mid-sitting, it resumes on the first unanswered question, and a failed submission keeps the
 * student's text so a retry costs a click rather than retyping it.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DiagnosticRunner } from '@/features/diagnostic/components/DiagnosticRunner';
import { ApiError } from '@/lib/api/client';
import type { SessionQuestion, SessionState } from '@/lib/api/sessions';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));

const submitAnswer = vi.fn();
const completeSession = vi.fn();
vi.mock('@/lib/api/sessions', () => ({
  submitAnswer: (...args: unknown[]) => submitAnswer(...args),
  completeSession: (...args: unknown[]) => completeSession(...args),
}));

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
    type: 'diagnostic',
    status: 'in_progress',
    question_count: 3,
    answered_count: 0,
    started_at: '2026-01-01T00:00:00Z',
    finished_at: null,
    selection_rationale: null,
    questions: [question(0), question(1), question(2)],
    resumed: false,
    ...overrides,
  };
}

const ANSWER = 'Subtract net debt from enterprise value and add back cash equivalents.';

/** Set the composer's value. fireEvent is enough here and keeps the dependency list unchanged. */
function type(value: string) {
  fireEvent.change(screen.getByLabelText('Your answer'), { target: { value } });
}

beforeEach(() => {
  push.mockReset();
  submitAnswer.mockReset().mockResolvedValue({ id: 'attempt-1', grading_status: 'pending' });
  completeSession.mockReset().mockResolvedValue(session({ status: 'completed' }));
});

describe('DiagnosticRunner', () => {
  it('shows the first question with its position and category', () => {
    render(<DiagnosticRunner session={session()} />);

    expect(screen.getByText(/Question 1 of 3 · Valuation/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Prompt number 0' })).toBeInTheDocument();
  });

  it('never reveals a grade during the sitting', async () => {
    render(<DiagnosticRunner session={session()} />);

    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(submitAnswer).toHaveBeenCalled());
    // A diagnostic is an assessment: a per-question score would let a student calibrate
    // mid-sitting and would drain the results page of its payoff.
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/strong|developing|needs work/i)).not.toBeInTheDocument();
  });

  it('advances to the next question after a submission', async () => {
    render(<DiagnosticRunner session={session()} />);

    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Prompt number 1' })).toBeInTheDocument(),
    );
  });

  it('clears the draft between questions', async () => {
    render(<DiagnosticRunner session={session()} />);

    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByLabelText('Your answer')).toHaveValue(''));
  });

  it('resumes on the first unanswered question', () => {
    render(
      <DiagnosticRunner
        session={session({
          answered_count: 1,
          questions: [
            question(0, { attempt_id: 'attempt-0', grading_status: 'graded' }),
            question(1),
            question(2),
          ],
        })}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Prompt number 1' })).toBeInTheDocument();
  });

  it('keeps the answer in the box when submission fails', async () => {
    // The network-failure path a student on campus wifi actually hits. Losing their text here
    // would be the worst possible moment to lose it.
    submitAnswer.mockRejectedValue(new ApiError(503, 'Could not reach the server.'));
    render(<DiagnosticRunner session={session()} />);

    type(ANSWER);
    fireEvent.click(screen.getByRole('button', { name: 'Submit answer' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByLabelText('Your answer')).toHaveValue(ANSWER);
    expect(screen.getByRole('alert')).toHaveTextContent(/still here/);
  });

  it('disables submitting until the answer has some substance', () => {
    render(<DiagnosticRunner session={session()} />);

    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeDisabled();

    type('no');
    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeDisabled();

    type(ANSWER);
    expect(screen.getByRole('button', { name: 'Submit answer' })).toBeEnabled();
  });

  it('offers to finish only when every question is answered', () => {
    render(
      <DiagnosticRunner
        session={session({
          answered_count: 3,
          questions: [
            question(0, { attempt_id: 'a0' }),
            question(1, { attempt_id: 'a1' }),
            question(2, { attempt_id: 'a2' }),
          ],
        })}
      />,
    );

    expect(screen.getByRole('button', { name: 'Finish and grade' })).toBeInTheDocument();
  });

  it('does not offer to finish while questions remain', () => {
    render(<DiagnosticRunner session={session()} />);

    expect(screen.queryByRole('button', { name: 'Finish and grade' })).not.toBeInTheDocument();
  });

  it('routes to results after finishing', async () => {
    render(
      <DiagnosticRunner
        session={session({
          questions: [
            question(0, { attempt_id: 'a0' }),
            question(1, { attempt_id: 'a1' }),
            question(2, { attempt_id: 'a2' }),
          ],
        })}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Finish and grade' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/diagnostic/session-1/results'));
  });

  it('reports how many questions remain', () => {
    render(<DiagnosticRunner session={session()} />);

    expect(screen.getByText(/3 questions left/)).toBeInTheDocument();
  });

  it('lets a student skip and come back through the progress rail', async () => {
    render(<DiagnosticRunner session={session()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(screen.getByRole('heading', { name: 'Prompt number 1' })).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Question 1, Valuation, not answered'));
    expect(screen.getByRole('heading', { name: 'Prompt number 0' })).toBeInTheDocument();
  });

  it('shows an already-answered question as answered rather than editable', () => {
    render(
      <DiagnosticRunner
        session={session({
          questions: [question(0, { attempt_id: 'a0' }), question(1), question(2)],
        })}
      />,
    );

    // Resumes on question 1; walk back to the answered one.
    fireEvent.click(screen.getByLabelText('Question 1, Valuation, answered'));

    expect(screen.getByRole('heading', { name: 'Prompt number 0' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument();
    expect(screen.getByText(/graded after you finish/)).toBeInTheDocument();
  });
});
