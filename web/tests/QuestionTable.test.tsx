/**
 * The question list is fetched constantly, so the property that matters most is what it does
 * *not* contain: no prompt, no ideal answer, no rubric.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { QuestionTable } from '@/features/admin/components/QuestionTable';
import type { AdminQuestion } from '@/lib/api/admin';

const CATEGORIES = [
  { slug: 'dcf', name: 'DCF', description: null, display_order: 4 },
];

function question(overrides: Partial<AdminQuestion> = {}): AdminQuestion {
  return {
    id: '018f0000-0000-7000-8000-000000000001',
    source_key: 'dcf-001-walkthrough',
    category_slug: 'dcf',
    subcategory: 'Mechanics',
    difficulty: 1,
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    published_version: {
      id: '018f0000-0000-7000-8000-000000000002',
      version: 2,
      status: 'published',
      created_by: null,
      created_at: '2026-01-01T00:00:00Z',
    },
    version_count: 3,
    ...overrides,
  };
}

describe('QuestionTable', () => {
  it('shows the category name rather than the raw slug', () => {
    render(<QuestionTable questions={[question()]} categories={CATEGORIES} />);

    expect(screen.getByRole('link', { name: 'DCF' })).toBeInTheDocument();
  });

  it('links each row to the question detail page', () => {
    render(<QuestionTable questions={[question()]} categories={CATEGORIES} />);

    expect(screen.getByRole('link', { name: 'DCF' })).toHaveAttribute(
      'href',
      '/admin/questions/018f0000-0000-7000-8000-000000000001',
    );
  });

  it('flags a question with no published version as ungradeable', () => {
    render(
      <QuestionTable
        questions={[question({ published_version: null, status: 'draft' })]}
        categories={CATEGORIES}
      />,
    );

    expect(screen.getByText('none')).toBeInTheDocument();
  });

  it('renders an empty state rather than a bare table', () => {
    render(<QuestionTable questions={[]} categories={CATEGORIES} />);

    expect(screen.getByText('No questions match these filters.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
