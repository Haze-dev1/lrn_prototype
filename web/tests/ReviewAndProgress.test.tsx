/**
 * Review turns evidence into something actionable; progress answers whether the student is
 * improving. These tests pin the claims those surfaces make — especially the one they must never
 * make, which is presenting an unmeasured category as a zero.
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CategoryProgressList } from '@/features/progress/components/CategoryProgressList';
import { MasteryTrend } from '@/features/progress/components/MasteryTrend';
import { FlagGradeControl } from '@/features/practice/components/FlagGradeControl';
import { ReviewList } from '@/features/review/components/ReviewList';
import { ApiError } from '@/lib/api/client';
import type { CategoryProgress, ReviewItem, TrendPoint } from '@/lib/api/review';

const flagGrade = vi.fn();
vi.mock('@/lib/api/review', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/review')>();
  return { ...actual, flagGrade: (...args: unknown[]) => flagGrade(...args) };
});

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 'attempt-1',
    question_id: 'question-1',
    category_slug: 'valuation',
    category_name: 'Valuation',
    difficulty: 3,
    prompt: 'How do you get from enterprise value to equity value?',
    score: 54,
    band: 'needs_work',
    concepts_missed: ['net_debt', 'cash'],
    submitted_at: '2026-06-01T12:00:00Z',
    flagged: false,
    ...overrides,
  };
}

function category(overrides: Partial<CategoryProgress> = {}): CategoryProgress {
  return {
    slug: 'valuation',
    name: 'Valuation',
    score: 54,
    previous_score: null,
    evidence_count: 5,
    last_attempt_at: '2026-06-01T12:00:00Z',
    provisional: false,
    ...overrides,
  };
}

function point(overall: number | null, week: number): TrendPoint {
  return { as_of: `2026-0${week}-01T00:00:00Z`, scores: {}, overall };
}

beforeEach(() => {
  flagGrade.mockReset().mockResolvedValue({ id: 'flag-1', status: 'open', already_flagged: false });
});

describe('ReviewList', () => {
  it('leads each row with the score', () => {
    render(<ReviewList items={[item()]} filtered={false} />);

    expect(screen.getByText('54')).toBeInTheDocument();
  });

  it('links each row to the answer in full', () => {
    render(<ReviewList items={[item()]} filtered={false} />);

    expect(screen.getByRole('link')).toHaveAttribute('href', '/review/attempt-1');
  });

  it('counts missed concepts so a row is worth opening', () => {
    render(<ReviewList items={[item()]} filtered={false} />);

    expect(screen.getByText('2 concepts missed')).toBeInTheDocument();
  });

  it('marks a flagged answer', () => {
    render(<ReviewList items={[item({ flagged: true })]} filtered={false} />);

    expect(screen.getByText('Flagged')).toBeInTheDocument();
  });

  it('carries no answer text, since a list is scanned not read', () => {
    const { container } = render(<ReviewList items={[item()]} filtered={false} />);

    expect(container.textContent).not.toContain('ideal answer');
    expect(screen.queryByText(/Your answer/)).not.toBeInTheDocument();
  });

  it('distinguishes an empty history from an empty filter result', () => {
    const { rerender } = render(<ReviewList items={[]} filtered={false} />);
    expect(screen.getByText('Nothing to review yet.')).toBeInTheDocument();

    rerender(<ReviewList items={[]} filtered />);
    expect(screen.getByText('No answers match these filters.')).toBeInTheDocument();
  });
});

describe('CategoryProgressList', () => {
  it('orders measured categories weakest first', () => {
    render(
      <CategoryProgressList
        categories={[
          category({ slug: 'dcf', name: 'DCF', score: 88 }),
          category({ slug: 'valuation', name: 'Valuation', score: 40 }),
        ]}
      />,
    );
    const names = screen.getAllByRole('link').map((link) => link.textContent);

    expect(names[0]).toBe('Valuation');
  });

  it('never renders an unmeasured category as a zero', () => {
    // "Not measured" and "measured badly" are different claims, and showing the first as the
    // second is a fabricated readiness signal — the one thing this product must not do.
    render(<CategoryProgressList categories={[category({ score: null, evidence_count: 0 })]} />);

    expect(screen.getByText('Not measured yet')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('marks a thin score as provisional', () => {
    render(<CategoryProgressList categories={[category({ evidence_count: 1, provisional: true })]} />);

    expect(screen.getByText('Provisional')).toBeInTheDocument();
    expect(screen.getByText(/1 graded answer/)).toBeInTheDocument();
  });

  it('shows movement against the previous score', () => {
    render(<CategoryProgressList categories={[category({ score: 70, previous_score: 55 })]} />);

    expect(screen.getByText('+15')).toBeInTheDocument();
  });

  it('links every category to practice for it', () => {
    render(<CategoryProgressList categories={[category()]} />);

    expect(screen.getByRole('link', { name: 'Valuation' })).toHaveAttribute(
      'href',
      '/practice?category=valuation',
    );
  });

  it('gives each score an accessible reading', () => {
    render(<CategoryProgressList categories={[category()]} />);

    expect(screen.getByLabelText('Valuation: 54 out of 100')).toBeInTheDocument();
  });
});

describe('MasteryTrend', () => {
  it('says so plainly when there is not enough history', () => {
    // A flat line and no data look identical on a chart; only one means the student has not moved.
    render(<MasteryTrend trend={[point(60, 1)]} movement={null} />);

    expect(screen.getByText(/Not enough history yet/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('draws a line once there are two measured points', () => {
    render(<MasteryTrend trend={[point(40, 1), point(62, 2)]} movement={22} />);

    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.getByText('62')).toBeInTheDocument();
  });

  it('reports movement with a sign', () => {
    render(<MasteryTrend trend={[point(40, 1), point(62, 2)]} movement={22} />);

    expect(screen.getByText(/\+22 over 2 weeks/)).toBeInTheDocument();
  });

  it('ignores weeks before the student had any evidence', () => {
    // Drawing them at zero would show a dramatic rise that is really just the moment they started.
    render(<MasteryTrend trend={[point(null, 1), point(null, 2), point(70, 3)]} movement={null} />);

    expect(screen.getByText(/Not enough history yet/)).toBeInTheDocument();
  });
});

describe('FlagGradeControl', () => {
  it('is understated until opened', () => {
    render(<FlagGradeControl attemptId="attempt-1" alreadyFlagged={false} />);

    expect(screen.getByRole('button', { name: 'Flag this grade' })).toBeInTheDocument();
    expect(screen.queryByLabelText('What is wrong with it?')).not.toBeInTheDocument();
  });

  it('collects a reason and sends it', async () => {
    render(<FlagGradeControl attemptId="attempt-1" alreadyFlagged={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Flag this grade' }));

    fireEvent.change(screen.getByLabelText('What is wrong with it?'), {
      target: { value: 'wrong_concepts' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() =>
      expect(flagGrade).toHaveBeenCalledWith('attempt-1', {
        reason: 'wrong_concepts',
        comment: null,
      }),
    );
  });

  it('collapses to an acknowledgement once raised', async () => {
    render(<FlagGradeControl attemptId="attempt-1" alreadyFlagged={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Flag this grade' }));
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(screen.getByText(/You flagged this grade/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
  });

  it('does not re-offer the control for an already flagged grade', () => {
    // A flag is a statement, not a vote; re-offering it would suggest repeating it does something.
    render(<FlagGradeControl attemptId="attempt-1" alreadyFlagged />);

    expect(screen.getByText(/You flagged this grade/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Flag this grade' })).not.toBeInTheDocument();
  });

  it('keeps the form open when sending fails', async () => {
    flagGrade.mockRejectedValue(new ApiError(503, 'Could not reach the server.'));
    render(<FlagGradeControl attemptId="attempt-1" alreadyFlagged={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Flag this grade' }));
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
  });
});

describe('review row bands', () => {
  it.each([
    [88, 'strong'],
    [60, 'developing'],
    [30, 'needs work'],
  ])('renders %i as %s', (score, label) => {
    const band = score >= 75 ? 'strong' : score >= 55 ? 'developing' : 'needs_work';
    render(<ReviewList items={[item({ score, band: band as ReviewItem['band'] })]} filtered={false} />);
    const row = screen.getByRole('listitem');

    expect(within(row).getByText(label)).toBeInTheDocument();
  });
});
