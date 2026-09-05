/**
 * Difficulty indicator.
 *
 * Three filled marks out of five, no label. The PRD calls for a *subtle* indicator: a student
 * needs to know a question is meant to be hard so a poor answer reads as a hard question rather
 * than personal failure, but a prominent "LEVEL 4 — EXPERT" badge would prime them to give up
 * before reading the prompt.
 */

const LEVELS = [1, 2, 3, 4, 5];

export interface DifficultyMeterProps {
  level: number;
}

export function DifficultyMeter({ level }: DifficultyMeterProps) {
  return (
    <span className="flex items-center gap-1.5" title={`Difficulty ${level} of 5`}>
      <span className="label-micro">Difficulty</span>
      <span className="flex gap-0.5" aria-label={`Difficulty ${level} of 5`} role="img">
        {LEVELS.map((mark) => (
          <span
            key={mark}
            aria-hidden="true"
            className={[
              'h-3 w-1 rounded-[1px]',
              mark <= level ? 'bg-text-secondary' : 'bg-surface-3',
            ].join(' ')}
          />
        ))}
      </span>
    </span>
  );
}
