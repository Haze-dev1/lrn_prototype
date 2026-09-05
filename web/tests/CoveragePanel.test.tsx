/**
 * The coverage panel is how a content owner learns the bank cannot yet compose a diagnostic.
 * These tests pin the two states that decision depends on.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CoveragePanel } from '@/features/admin/components/CoveragePanel';
import type { BankCoverage } from '@/lib/api/admin';

function coverage(overrides: Partial<BankCoverage> = {}): BankCoverage {
  return {
    categories: [
      { slug: 'accounting', name: 'Accounting', selectable: 5, required: 3, shortfall: 0 },
      { slug: 'dcf', name: 'DCF', selectable: 1, required: 3, shortfall: 2 },
    ],
    total_selectable: 6,
    diagnostic_ready: false,
    counts_by_status: { draft: 1, active: 6, retired: 0 },
    ...overrides,
  };
}

describe('CoveragePanel', () => {
  it('reports that the bank is not ready and how many categories are short', () => {
    render(<CoveragePanel coverage={coverage()} />);

    expect(screen.getByText('Not ready')).toBeInTheDocument();
    expect(screen.getByText(/1 category is short of what a diagnostic needs/)).toBeInTheDocument();
  });

  it('pluralises the summary when several categories are short', () => {
    render(
      <CoveragePanel
        coverage={coverage({
          categories: [
            { slug: 'dcf', name: 'DCF', selectable: 0, required: 3, shortfall: 3 },
            { slug: 'lbo', name: 'LBO', selectable: 1, required: 3, shortfall: 2 },
          ],
        })}
      />,
    );

    expect(screen.getByText(/2 categories are short/)).toBeInTheDocument();
  });

  it('names the shortfall for a thin category', () => {
    render(<CoveragePanel coverage={coverage()} />);

    expect(screen.getByText('2 short')).toBeInTheDocument();
  });

  it('puts the category with the largest shortfall first', () => {
    render(<CoveragePanel coverage={coverage()} />);
    const names = screen.getAllByRole('listitem').map((item) => item.textContent);

    expect(names[0]).toContain('DCF');
  });

  it('reports readiness when every category is covered', () => {
    render(
      <CoveragePanel
        coverage={coverage({
          categories: [
            { slug: 'accounting', name: 'Accounting', selectable: 5, required: 3, shortfall: 0 },
          ],
          diagnostic_ready: true,
        })}
      />,
    );

    expect(screen.getByText('Diagnostic ready')).toBeInTheDocument();
    expect(screen.getByText(/The diagnostic can be composed/)).toBeInTheDocument();
  });
});
