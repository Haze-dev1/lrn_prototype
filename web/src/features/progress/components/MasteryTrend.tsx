import type { TrendPoint } from '@/lib/api/review';

export interface MasteryTrendProps {
  trend: TrendPoint[];
  movement: number | null;
}

/**
 * Overall mastery over the recent weeks.
 *
 * A single sparkline of one number, not a chart per category. The question this answers is "am I
 * improving", and eight overlapping lines answer it worse than one — the student would have to
 * do the aggregation themselves to get back to the thing they wanted to know.
 *
 * Drawn as inline SVG rather than pulling in a charting library for one polyline. Weeks before
 * the student had any evidence are simply absent from the line: drawing them at zero would show
 * a dramatic rise that is really just the moment they started.
 */
export function MasteryTrend({ trend, movement }: MasteryTrendProps) {
  const measured = trend.filter((point) => point.overall !== null);

  if (measured.length < 2) {
    return (
      <section
        aria-labelledby="trend-heading"
        className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5"
      >
        <h2 id="trend-heading" className="label-micro">
          Are you improving?
        </h2>
        <p className="mt-3 text-sm text-text-secondary">
          Not enough history yet. Come back after another session and this will show how your
          overall mastery has moved.
        </p>
      </section>
    );
  }

  const width = 100;
  const height = 28;
  const values = measured.map((point) => point.overall ?? 0);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 100);
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / (max - min || 1)) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  const latest = values[values.length - 1] ?? 0;
  const rising = (movement ?? 0) > 0;

  return (
    <section
      aria-labelledby="trend-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="trend-heading" className="label-micro">
          Are you improving?
        </h2>
        {movement !== null ? (
          <p
            className={[
              'tabular text-sm',
              movement > 0 ? 'text-band-strong' : movement < 0 ? 'text-band-needs-work' : 'text-text-muted',
            ].join(' ')}
          >
            {movement > 0 ? '+' : ''}
            {movement} over {measured.length} weeks
          </p>
        ) : null}
      </div>

      <div className="mt-4 flex items-end gap-4">
        <p className="tabular text-4xl font-semibold text-text-primary">{latest}</p>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="h-12 flex-1"
          role="img"
          aria-label={`Overall mastery over the last ${measured.length} weeks, currently ${latest}`}
        >
          <polyline
            points={points}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
            className={rising ? 'text-band-strong' : 'text-accent'}
          />
        </svg>
      </div>
    </section>
  );
}
