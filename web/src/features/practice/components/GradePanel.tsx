'use client';

import { Alert } from '@/components/ui/Alert';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { FlagGradeControl } from '@/features/practice/components/FlagGradeControl';
import type { Band, GradedAttempt } from '@/lib/api/sessions';
import { CheckCircle2, XCircle, AlertTriangle, Lightbulb, ChevronRight, BookOpen } from 'lucide-react';

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
    <section aria-labelledby="grade-heading" className="flex flex-col gap-12 animate-in fade-in slide-in-from-bottom-4 duration-500 pt-8 border-t border-border-subtle">
      <h2 id="grade-heading" className="sr-only">Your grade</h2>

      {/* Score Header */}
      <div className="flex flex-col md:flex-row items-baseline gap-6 relative">
        <div className="flex flex-col gap-1">
          <p className="label-micro text-text-muted">EVALUATION SCORE</p>
          <div className="flex items-baseline gap-2">
            <p className={`tabular text-8xl font-light tracking-tight ${SCORE_COLOUR[attempt.band]}`}>
              {attempt.score}
            </p>
            <span className="text-xl text-text-muted font-light">/ 100</span>
          </div>
        </div>
        <div className="md:ml-4">
          <Badge tone={tone} className="px-4 py-1.5 text-sm font-medium rounded-full">
            {BAND_LABEL[attempt.band]}
          </Badge>
        </div>
      </div>

      <div className="w-12 h-[1px] bg-border-strong" />

      {/* Concept Breakdown */}
      <div className="grid gap-12 md:grid-cols-2">
        {/* Hits */}
        <div className="space-y-5">
          <h3 className="label-micro text-text-primary">WHAT YOU GOT RIGHT</h3>
          {attempt.concepts_hit.length > 0 ? (
            <ul className="space-y-3">
              {attempt.concepts_hit.map((key) => (
                <li key={key} className="text-base text-text-secondary pl-6 relative leading-relaxed">
                  <span className="absolute left-0 top-2.5 w-1.5 h-1.5 rounded-full bg-band-strong" />
                  {label(key)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-base text-text-muted italic">None of the expected concepts.</p>
          )}
        </div>

        {/* Misses & Mistakes */}
        <div className="space-y-10">
          <div className="space-y-5">
            <h3 className="label-micro text-text-primary">WHAT YOU MISSED</h3>
            {attempt.concepts_missed.length > 0 ? (
              <ul className="space-y-3">
                {attempt.concepts_missed.map((key) => (
                  <li key={key} className="text-base text-text-secondary pl-6 relative leading-relaxed">
                    <span className="absolute left-0 top-2.5 w-1.5 h-1.5 rounded-full bg-band-needs-work" />
                    {label(key)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-base text-text-muted italic">You covered everything expected.</p>
            )}
          </div>
          
          {attempt.mistake_flags.length > 0 && (
            <div className="space-y-5">
              <h3 className="label-micro text-text-primary">MISTAKES TO AVOID</h3>
              <ul className="space-y-3">
                {attempt.mistake_flags.map((key) => (
                  <li key={key} className="text-base text-text-secondary pl-6 relative leading-relaxed">
                    <span className="absolute left-0 top-2.5 w-1.5 h-1.5 rounded-full bg-band-developing" />
                    {label(key)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="w-12 h-[1px] bg-border-strong" />

      {/* Coaching */}
      <div className="space-y-4 max-w-2xl">
        <h3 className="label-micro text-accent">WHAT TO IMPROVE</h3>
        <p className="text-lg leading-relaxed text-text-primary font-medium">
          {attempt.feedback}
        </p>
      </div>

      {/* Reference answer */}
      <div className="max-w-2xl pt-4">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-text-muted hover:text-text-primary transition-colors focus-visible:outline-none">
            <span className="border-b border-dashed border-text-muted group-hover:border-text-primary transition-colors">
              Read reference answer
            </span>
          </summary>
          <div className="mt-6 pt-6 border-t border-border-subtle animate-in fade-in slide-in-from-top-2 duration-300">
            <p className="text-base leading-relaxed text-text-secondary whitespace-pre-wrap font-serif">
              {attempt.ideal_answer}
            </p>
          </div>
        </details>
      </div>

      <div className="pt-8 flex items-center">
        <FlagGradeControl attemptId={attempt.id} alreadyFlagged={attempt.flagged} />
      </div>
    </section>
  );
}

export function GradingPending({ failed }: { failed: boolean }) {
  if (failed) {
    return (
      <Alert tone="info">
        This answer could not be graded right now. It is saved and will be graded automatically — your score will appear in your history shortly.
      </Alert>
    );
  }

  return (
    <div
      aria-live="polite"
      className="rounded-[--radius-lg] border border-border-subtle bg-surface-1 px-8 py-12 flex flex-col items-center text-center animate-pulse"
    >
      <div className="w-12 h-12 rounded-full bg-accent/20 flex items-center justify-center mb-4">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
      <p className="label-micro text-accent mb-2">Grading</p>
      <p className="text-sm text-text-secondary max-w-sm">
        Your answer is being read against the rubric. This usually takes a few seconds.
      </p>
    </div>
  );
}
