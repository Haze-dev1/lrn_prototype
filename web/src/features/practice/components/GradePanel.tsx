'use client';

import { Alert } from '@/components/ui/Alert';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { FlagGradeControl } from '@/features/practice/components/FlagGradeControl';
import type { Band, GradedAttempt } from '@/lib/api/sessions';

const BAND_TONE: Record<Band, BadgeTone> = {
  strong: 'strong',
  developing: 'developing',
  needs_work: 'needs-work',
};

const BAND_LABEL: Record<Band, string> = {
  strong: 'Strong',
  developing: 'Developing',
  needs_work: 'Needs work',
};

const SCORE_COLOUR: Record<Band, string> = {
  strong: 'text-band-strong',
  developing: 'text-band-developing',
  needs_work: 'text-band-needs-work',
};

export interface GradePanelProps {
  attempt: GradedAttempt;
  /** Concept and mistake labels, so keys are never shown to a student. */
  labels: Record<string, string>;
}

/**
 * A graded answer.
 *
 * Structured as score, band, evidence, then coaching — the order a student reads it in, and the
 * order that makes the score defensible rather than arbitrary. The concepts are the argument for
 * the number, which is why they sit between the two.
 *
 * The reference answer is shown last and only here, after submission. Before that it is the
 * answer key; after it is the most useful thing on the page.
 */
export function GradePanel({ attempt, labels }: GradePanelProps) {
  const tone = BAND_TONE[attempt.band];
  const label = (key: string) => labels[key] ?? key.replace(/_/g, ' ');

  return (
    <section aria-labelledby="grade-heading" className="space-y-6">
      <h2 id="grade-heading" className="sr-only">
        Your grade
      </h2>

      <div className="flex items-end justify-between gap-4 border-b border-border-subtle pb-5">
        <div>
          <p className="label-micro">Score</p>
          <p className={`tabular mt-1 text-6xl font-semibold ${SCORE_COLOUR[attempt.band]}`}>
            {attempt.score}
          </p>
        </div>
        <Badge tone={tone}>{BAND_LABEL[attempt.band]}</Badge>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <p className="label-micro">Concepts you showed</p>
          {attempt.concepts_hit.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {attempt.concepts_hit.map((key) => (
                <li key={key} className="flex gap-2 text-sm text-text-secondary">
                  <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-band-strong" />
                  {label(key)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-text-muted">None of the expected concepts.</p>
          )}
        </div>

        <div>
          <p className="label-micro">Concepts you missed</p>
          {attempt.concepts_missed.length > 0 ? (
            <ul className="mt-3 space-y-1.5">
              {attempt.concepts_missed.map((key) => (
                <li key={key} className="flex gap-2 text-sm text-text-secondary">
                  <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-band-needs-work" />
                  {label(key)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-band-strong">You covered everything expected.</p>
          )}
        </div>
      </div>

      {attempt.mistake_flags.length > 0 ? (
        <div>
          <p className="label-micro">Mistakes</p>
          <ul className="mt-3 space-y-1.5">
            {attempt.mistake_flags.map((key) => (
              <li key={key} className="flex gap-2 text-sm text-band-developing">
                <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-band-developing" />
                {label(key)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <p className="label-micro">Coaching</p>
        <p className="mt-3 text-sm leading-relaxed text-text-primary">{attempt.feedback}</p>
      </div>

      <div className="border-t border-border-subtle pt-4">
        <FlagGradeControl attemptId={attempt.id} alreadyFlagged={attempt.flagged} />
      </div>

      <details className="group rounded-[--radius-card] border border-border-subtle bg-surface-1">
        <summary className="cursor-pointer list-none px-5 py-3 text-sm text-text-secondary hover:text-text-primary">
          <span className="label-micro">Reference answer</span>
        </summary>
        <p className="border-t border-border-subtle px-5 py-4 text-sm leading-relaxed text-text-secondary">
          {attempt.ideal_answer}
        </p>
      </details>
    </section>
  );
}

/** Shown while an answer is being graded. No fake typing, no invented progress. */
export function GradingPending({ failed }: { failed: boolean }) {
  if (failed) {
    return (
      <Alert tone="info">
        This answer could not be graded. It is saved and will be graded automatically — your score
        will appear in your history shortly.
      </Alert>
    );
  }

  return (
    <div
      aria-live="polite"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 px-5 py-8 text-center"
    >
      <p className="label-micro">Grading</p>
      <p className="mt-3 text-sm text-text-secondary">
        Your answer is being read against the rubric. This usually takes a few seconds.
      </p>
    </div>
  );
}
