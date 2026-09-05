const CATEGORIES = [
  { name: 'Accounting', score: 81 },
  { name: 'Enterprise & equity value', score: 74 },
  { name: 'Valuation', score: 54 },
  { name: 'DCF', score: 62 },
  { name: 'M&A / merger modelling', score: 48 },
  { name: 'LBO & private equity', score: 45 },
  { name: 'Financial statement analysis', score: 77 },
  { name: 'Markets, deals & judgment', score: null },
];

function toneFor(score: number): string {
  if (score >= 75) return 'bg-band-strong';
  if (score >= 55) return 'bg-band-developing';
  return 'bg-band-needs-work';
}

/**
 * Mastery across the eight categories.
 *
 * The last row is deliberately unmeasured. It is the honest state — a student who has not been
 * asked about something has no score in it — and rendering it as "Not measured yet" rather than
 * as a zero is a rule the product enforces everywhere, because "we did not ask" and "you did
 * badly" are different claims and only one of them is true. Showing that here, on the page that
 * sets expectations, is the point rather than an omission.
 */
export function MasteryDemo() {
  return (
    <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6 md:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="label-micro">Category mastery</p>
        <p className="label-micro">After the diagnostic</p>
      </div>

      <ul className="mt-5 space-y-3.5">
        {CATEGORIES.map((category) => (
          <li key={category.name} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 sm:grid-cols-[13rem_1fr_auto]">
            <span className="text-sm text-text-secondary">{category.name}</span>

            <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-surface-3 sm:col-span-1">
              {category.score === null ? null : (
                <span
                  className={`block h-full rounded-full ${toneFor(category.score)}`}
                  style={{ width: `${category.score}%` }}
                />
              )}
            </span>

            <span
              className={`tabular text-right font-mono text-sm ${
                category.score === null ? 'text-text-muted' : 'text-text-primary'
              }`}
            >
              {category.score ?? 'Not measured yet'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
