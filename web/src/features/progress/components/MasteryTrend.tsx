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
export function MasteryTrend({ trend, movement, sparklineOnly }: MasteryTrendProps & { sparklineOnly?: boolean }) {
  const measured = trend.filter((point) => point.overall !== null);

  if (measured.length < 2) {
    return (
      <div className="flex flex-col">
        <p className="text-sm text-text-secondary">
          Not enough history yet.
        </p>
      </div>
    );
  }

  const width = 100;
  const height = 40;
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

  const rising = (movement ?? 0) > 0;
  const strokeColor = rising ? 'currentColor' : 'currentColor';

  const latestValue = values[values.length - 1] ?? 0;
  
  return (
    <div className="flex flex-col w-full h-full justify-end">
      {!sparklineOnly && movement !== null ? (
        <div className="flex items-baseline justify-between gap-4 mb-4">
          <p
            className={[
              'tabular text-sm font-medium',
              movement > 0 ? 'text-band-strong' : movement < 0 ? 'text-band-needs-work' : 'text-text-muted',
            ].join(' ')}
          >
            {movement > 0 ? '+' : ''}
            {movement} points over {measured.length} weeks
          </p>
        </div>
      ) : null}

      <div className="flex items-end h-full relative">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="h-full w-full overflow-visible"
          role="img"
          aria-label="Overall mastery trend"
        >
          <defs>
            <linearGradient id="sparkline-gradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.2" />
              <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polyline
            points={`${points} ${width},${height} 0,${height}`}
            fill="url(#sparkline-gradient)"
            className="text-accent/20"
          />
          <polyline
            points={points}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            className={rising ? 'text-band-strong' : 'text-text-primary opacity-60'}
          />
          {/* Latest point dot */}
          <circle 
            cx={width} 
            cy={height - ((latestValue - min) / (max - min || 1)) * height} 
            r="2.5" 
            fill="currentColor" 
            className={rising ? 'text-band-strong' : 'text-text-primary'}
          />
        </svg>
      </div>
    </div>
  );
}
