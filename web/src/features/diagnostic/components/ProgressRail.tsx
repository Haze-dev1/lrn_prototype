'use client';

import type { SessionQuestion } from '@/lib/api/sessions';

export interface ProgressRailProps {
  total: number;
  questions: SessionQuestion[];
  answeredIds: Set<string>;
  currentIndex: number;
  /** Omitted while a request is in flight, which renders the rail read-only. */
  onJump?: (index: number) => void;
}

/**
 * Assessment progress.
 *
 * One mark per question rather than a percentage bar. A student mid-diagnostic wants to know how
 * much is left and whether they skipped anything — a bar answers the first and hides the second.
 * Marks are also the navigation, so returning to a skipped question costs one click.
 */
export function ProgressRail({
  total,
  questions,
  answeredIds,
  currentIndex,
  onJump,
}: ProgressRailProps) {
  const answered = answeredIds.size;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <p className="label-micro">Progress</p>
        <p className="tabular text-xs text-text-muted">
          {answered} of {total} answered
        </p>
      </div>

      <div className="flex gap-1" role="list">
        {questions.map((question, index) => {
          const isAnswered = answeredIds.has(question.id);
          const isCurrent = index === currentIndex;
          const label = `Question ${index + 1}, ${question.category_name}, ${
            isAnswered ? 'answered' : 'not answered'
          }`;

          return (
            <button
              key={question.id}
              type="button"
              role="listitem"
              aria-label={label}
              aria-current={isCurrent ? 'step' : undefined}
              disabled={!onJump}
              onClick={() => onJump?.(index)}
              className={[
                'h-1.5 flex-1 rounded-full transition-colors',
                'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent',
                'disabled:cursor-default',
                isCurrent
                  ? 'bg-accent'
                  : isAnswered
                    ? 'bg-text-muted hover:bg-text-secondary'
                    : 'bg-surface-3 hover:bg-border-strong',
              ].join(' ')}
            />
          );
        })}
      </div>
    </div>
  );
}
