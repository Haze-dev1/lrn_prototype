/**
 * The version editor seeds its form from the version it is given.
 *
 * The switching test is a regression test for a real bug: the editor seeds its state in a
 * `useState` initialiser, which does not re-run when the prop changes, so a client-side
 * navigation between two versions of the same question showed the previous version's content.
 * The page fixes it by keying the editor on the version ID — that key is part of the contract,
 * and this test fails without it.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { VersionEditor } from '@/features/admin/components/VersionEditor';
import type { QuestionVersion } from '@/lib/api/admin';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

function version(overrides: Partial<QuestionVersion> = {}): QuestionVersion {
  return {
    id: 'version-1',
    question_id: 'question-1',
    version: 1,
    status: 'draft',
    prompt: 'Walk me through a DCF.',
    ideal_answer: 'Project unlevered free cash flow and discount it at WACC.',
    expected_concepts: [{ key: 'unlevered_fcf', label: 'Unlevered free cash flow' }],
    common_mistakes: [{ key: 'levered_at_wacc', label: 'Discounting levered cash flow at WACC' }],
    rubric: { band_thresholds: { strong: 80, developing: 55 } },
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

/** Mirrors how the page renders the editor, including the key that resets its state. */
function Page({ selected }: { selected: QuestionVersion }) {
  return <VersionEditor key={selected.id} questionId="question-1" version={selected} />;
}

describe('VersionEditor', () => {
  it('populates the form from the version it is given', () => {
    render(<VersionEditor questionId="question-1" version={version()} />);

    expect(screen.getByLabelText('Prompt')).toHaveValue('Walk me through a DCF.');
    expect(screen.getByLabelText('Ideal answer')).toHaveValue(
      'Project unlevered free cash flow and discount it at WACC.',
    );
    expect(screen.getByDisplayValue('unlevered_fcf')).toBeInTheDocument();
  });

  it('shows the new content when the selected version changes', () => {
    const { rerender } = render(<Page selected={version()} />);
    expect(screen.getByLabelText('Prompt')).toHaveValue('Walk me through a DCF.');

    rerender(
      <Page
        selected={version({
          id: 'version-2',
          version: 2,
          prompt: 'Walk me through an LBO.',
        })}
      />,
    );

    expect(screen.getByLabelText('Prompt')).toHaveValue('Walk me through an LBO.');
    expect(screen.getByText('Version 2')).toBeInTheDocument();
  });

  it('renders an empty form when authoring a new version', () => {
    render(<VersionEditor questionId="question-1" version={null} />);

    expect(screen.getByLabelText('Prompt')).toHaveValue('');
    expect(screen.getByText('New version')).toBeInTheDocument();
  });

  it('explains that a published version cannot be edited', () => {
    render(
      <VersionEditor questionId="question-1" version={version({ status: 'published' })} />,
    );

    expect(screen.getByText(/cannot be edited/)).toBeInTheDocument();
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
  });

  it('does not present a published version as editable in the save action', () => {
    render(
      <VersionEditor questionId="question-1" version={version({ status: 'superseded' })} />,
    );

    expect(screen.getByRole('button', { name: 'Save as new version' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save draft' })).not.toBeInTheDocument();
  });

  it('offers a draft the in-place save action', () => {
    render(<VersionEditor questionId="question-1" version={version()} />);

    expect(screen.getByRole('button', { name: 'Save draft' })).toBeInTheDocument();
  });

  it('disables publishing until a prompt and an ideal answer exist', () => {
    render(<VersionEditor questionId="question-1" version={null} />);

    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled();
  });

  it('renders the rubric as formatted JSON so it can be edited', () => {
    render(<VersionEditor questionId="question-1" version={version()} />);

    expect(screen.getByLabelText('Rubric')).toHaveValue(
      JSON.stringify({ band_thresholds: { strong: 80, developing: 55 } }, null, 2),
    );
  });
});
