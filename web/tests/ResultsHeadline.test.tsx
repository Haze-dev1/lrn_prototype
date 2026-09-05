/**
 * The results page's job is to make the weakest area unmissable and name one next action.
 * These tests pin that, not the styling.
 */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CategoryBreakdown } from '@/features/results/components/CategoryBreakdown';
import { ResultsHeadline } from '@/features/results/components/ResultsHeadline';
import { bandForScore } from '@/features/results/components/ScoreBar';
import type { CategoryResult } from '@/lib/api/sessions';

function category(overrides: Partial<CategoryResult> = {}): CategoryResult {
  return {
    slug: 'valuation',
    name: 'Valuation',
    score: 70,
    previous_score: null,
    evidence_count: 3,
    session_scores: [65, 70, 75],
    answered: 3,
    missed_concepts: [],
    ...overrides,
  };
}

const CATEGORIES: CategoryResult[] = [
  category({ slug: 'dcf', name: 'DCF', score: 88, session_scores: [85, 88, 91] }),
  category({
    slug: 'valuation',
    name: 'Valuation',
    score: 54,
    session_scores: [50, 54, 58],
    missed_concepts: ['net_debt', 'cash'],
  }),
  category({ slug: 'accounting', name: 'Accounting', score: 71, session_scores: [68, 71, 74] }),
];

const RECOMMENDATION = {
  action: 'practise_category',
  category_slug: 'valuation',
  category_name: 'Valuation',
  reason: 'Valuation is your weakest category at 54. You missed 2 expected concepts there.',
};

describe('ResultsHeadline', () => {
  it('leads with the weakest area, not the strongest', () => {
    // A results page that opens with what you are good at is flattering and useless.
    render(<ResultsHeadline categories={CATEGORIES} recommendation={RECOMMENDATION} />);

    expect(screen.getByText('Weakest area')).toBeInTheDocument();
    expect(screen.getByText('Valuation')).toBeInTheDocument();
    expect(screen.getByText('54')).toBeInTheDocument();
  });

  it('names the strongest area too', () => {
    render(<ResultsHeadline categories={CATEGORIES} recommendation={RECOMMENDATION} />);

    expect(screen.getByText('Strongest area')).toBeInTheDocument();
    expect(screen.getByText('DCF')).toBeInTheDocument();
  });

  it('averages across every category', () => {
    render(<ResultsHeadline categories={CATEGORIES} recommendation={RECOMMENDATION} />);

    expect(screen.getByText('71')).toBeInTheDocument();
  });

  it('shows exactly one next action', () => {
    // Five equally weighted options is how a student closes the tab without doing any of them.
    render(<ResultsHeadline categories={CATEGORIES} recommendation={RECOMMENDATION} />);

    expect(screen.getByText('Do this next')).toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('shows the recommendation reason in plain language', () => {
    render(<ResultsHeadline categories={CATEGORIES} recommendation={RECOMMENDATION} />);

    expect(screen.getByText(RECOMMENDATION.reason)).toBeInTheDocument();
  });

  it('renders without a recommendation', () => {
    render(<ResultsHeadline categories={CATEGORIES} recommendation={null} />);

    expect(screen.queryByText('Do this next')).not.toBeInTheDocument();
    expect(screen.getByText('Weakest area')).toBeInTheDocument();
  });

  it('renders nothing when there are no categories', () => {
    const { container } = render(<ResultsHeadline categories={[]} recommendation={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('CategoryBreakdown', () => {
  it('orders categories weakest first', () => {
    // The thing to act on is at the top, so a student does not scan eight rows to find it.
    render(<CategoryBreakdown categories={CATEGORIES} />);
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);

    expect(headings).toEqual(['Valuation', 'Accounting', 'DCF']);
  });

  it('shows this session‘s scores as the evidence behind the number', () => {
    render(<CategoryBreakdown categories={CATEGORIES} />);

    expect(screen.getByText(/50 · 54 · 58/)).toBeInTheDocument();
  });

  it('labels the scores neutrally, since practice renders this too', () => {
    // The same breakdown appears on the practice summary, where calling it a diagnostic is
    // simply untrue.
    render(<CategoryBreakdown categories={CATEGORIES} />);

    expect(screen.getAllByText(/This session:/).length).toBe(CATEGORIES.length);
    expect(screen.queryByText(/This diagnostic/)).not.toBeInTheDocument();
  });

  it('counts missed concepts', () => {
    render(<CategoryBreakdown categories={CATEGORIES} />);

    expect(screen.getByText('2 concepts missed')).toBeInTheDocument();
  });

  it('says so when a strong category had full coverage', () => {
    render(<CategoryBreakdown categories={[category({ score: 88, missed_concepts: [] })]} />);

    expect(screen.getByText('Full concept coverage')).toBeInTheDocument();
  });

  it('does not claim full coverage for a category that scored badly', () => {
    // An empty missed list also happens when grading failed or every concept key was rejected.
    // "Full concept coverage" beside a score of 0 is a contradiction, and a student would be
    // right not to trust anything else on the page after reading it.
    render(<CategoryBreakdown categories={[category({ score: 0, missed_concepts: [] })]} />);

    expect(screen.queryByText('Full concept coverage')).not.toBeInTheDocument();
  });

  it('shows movement against the previous score', () => {
    render(<CategoryBreakdown categories={[category({ score: 70, previous_score: 58 })]} />);

    expect(screen.getByText('+12')).toBeInTheDocument();
  });

  it('omits movement when there is no previous score', () => {
    render(<CategoryBreakdown categories={[category({ previous_score: null })]} />);

    expect(screen.queryByText(/^[+-]\d+$/)).not.toBeInTheDocument();
  });

  it('gives every category an accessible score reading', () => {
    render(<CategoryBreakdown categories={CATEGORIES} />);

    expect(screen.getByLabelText('Valuation: 54 out of 100')).toBeInTheDocument();
  });

  it('bands a weak category as needs work', () => {
    render(<CategoryBreakdown categories={[category({ score: 54 })]} />);
    const row = screen.getByRole('listitem');

    expect(within(row).getByText('Needs work')).toBeInTheDocument();
  });
});

describe('bandForScore', () => {
  it.each([
    [100, 'strong'],
    [75, 'strong'],
    [74, 'developing'],
    [65, 'developing'],
    [64, 'needs-work'],
    [0, 'needs-work'],
  ])('maps %i to %s', (score, expected) => {
    expect(bandForScore(score)).toBe(expected);
  });
});
