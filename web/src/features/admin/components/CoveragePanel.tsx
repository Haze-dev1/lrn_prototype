/**
 * Question bank readiness.
 *
 * Answers the one question a content owner actually has — can the bank compose a diagnostic, and
 * where are the gaps — rather than showing a grid of counts. Categories that are short appear
 * first and carry the only colour on the panel, so the work to do is the thing you see.
 */

import { Badge } from '@/components/ui/Badge';
import type { BankCoverage } from '@/lib/api/admin';

export interface CoveragePanelProps {
  coverage: BankCoverage;
}

export function CoveragePanel({ coverage }: CoveragePanelProps) {
  const gaps = coverage.categories.filter((row) => row.shortfall > 0);
  // Short categories first, deepest shortfall at the top; everything else keeps display order.
  const ordered = [...coverage.categories].sort((a, b) => b.shortfall - a.shortfall);

  // Built as one string rather than interpolated inline, so the sentence is a single text node
  // and reads as one phrase to a screen reader instead of three fragments.
  const summary = coverage.diagnostic_ready
    ? 'Every category has enough gradeable questions. The diagnostic can be composed.'
    : `${gaps.length} ${gaps.length === 1 ? 'category is' : 'categories are'} short of what a ` +
      'diagnostic needs.';

  return (
    <section
      aria-labelledby="coverage-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-border-subtle px-5 py-4">
        <div>
          <h2 id="coverage-heading" className="label-micro">
            Bank coverage
          </h2>
          <p className="mt-2 text-sm text-text-secondary">{summary}</p>
        </div>

        <div className="flex items-center gap-3">
          <Badge tone={coverage.diagnostic_ready ? 'strong' : 'needs-work'}>
            {coverage.diagnostic_ready ? 'Diagnostic ready' : 'Not ready'}
          </Badge>
          <p className="tabular text-sm text-text-muted">
            {coverage.total_selectable} gradeable
          </p>
        </div>
      </header>

      <ul className="divide-y divide-border-subtle">
        {ordered.map((row) => (
          <li key={row.slug} className="flex items-center justify-between gap-4 px-5 py-3">
            <span className="truncate text-sm text-text-secondary">{row.name}</span>
            <span className="flex shrink-0 items-center gap-3">
              <span
                className={[
                  'tabular text-sm',
                  row.shortfall > 0 ? 'text-band-needs-work' : 'text-text-primary',
                ].join(' ')}
              >
                {row.selectable}
              </span>
              <span className="w-24 text-right text-xs text-text-muted">
                {row.shortfall > 0 ? `${row.shortfall} short` : 'ready'}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
