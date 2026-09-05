/**
 * A category's mastery score.
 *
 * The bar is the only saturated colour on the results page, and it is band-coloured, so a weak
 * category is visible from across the room without reading a number. That is the page's whole
 * job: a student must leave knowing their weakest area even if they read nothing.
 */

export type Band = 'strong' | 'developing' | 'needs-work';

export function bandForScore(score: number): Band {
  if (score >= 75) return 'strong';
  if (score >= 65) return 'developing';
  return 'needs-work';
}

const BAR_COLOUR: Record<Band, string> = {
  strong: 'bg-band-strong',
  developing: 'bg-band-developing',
  'needs-work': 'bg-band-needs-work',
};

const TEXT_COLOUR: Record<Band, string> = {
  strong: 'text-band-strong',
  developing: 'text-band-developing',
  'needs-work': 'text-band-needs-work',
};

export interface ScoreBarProps {
  score: number;
  label: string;
}

export function ScoreBar({ score, label }: ScoreBarProps) {
  const band = bandForScore(score);

  return (
    <div className="flex items-center gap-3">
      <div
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3"
        role="img"
        aria-label={`${label}: ${score} out of 100`}
      >
        <div
          className={`h-full rounded-full ${BAR_COLOUR[band]}`}
          style={{ width: `${Math.max(score, 2)}%` }}
        />
      </div>
      <span className={`tabular w-8 text-right text-sm font-medium ${TEXT_COLOUR[band]}`}>
        {score}
      </span>
    </div>
  );
}
