'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { DifficultyMeter } from '@/features/diagnostic/components/DifficultyMeter';
import {
  MIN_USEFUL_LENGTH,
  QuestionComposer,
} from '@/features/diagnostic/components/QuestionComposer';
import { ProgressRail } from '@/features/diagnostic/components/ProgressRail';
import { GradePanel, GradingPending } from '@/features/practice/components/GradePanel';
import { PaywallNotice } from '@/features/billing/components/PaywallNotice';
import { paywallDetail, type PaywallDetail } from '@/lib/api/billing';
import { ApiError } from '@/lib/api/client';
import {
  completeSession,
  fetchAttempt,
  isGraded,
  submitAnswer,
  type GradedAttempt,
  type SessionState,
} from '@/lib/api/sessions';

const POLL_INTERVAL_MS = 1000;
// Roughly 30 seconds. Past that the retry sweep owns it and the student should not be held here.
const MAX_POLLS = 30;

export interface PracticeRunnerProps {
  session: SessionState;
}

/**
 * A practice session.
 *
 * The opposite of the diagnostic in the one way that matters: practice reveals the grade for each
 * answer immediately. Learning from a single answer is the whole point here, and deferring the
 * feedback to the end would turn a study tool into a second assessment.
 *
 * There is no fake typing animation while grading runs. What is shown is a plain statement that
 * the answer is being read, because that is true and a student who has just committed an answer
 * is owed honesty rather than a performance.
 */
export function PracticeRunner({ session }: PracticeRunnerProps) {
  const router = useRouter();
  const questions = session.questions;

  const [index, setIndex] = useState(() => {
    const next = questions.findIndex((q) => !q.attempt_id);
    return next === -1 ? 0 : next;
  });
  const [answered, setAnswered] = useState<Set<string>>(
    () => new Set(questions.filter((q) => q.attempt_id).map((q) => q.id)),
  );
  const [draft, setDraft] = useState('');
  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [grade, setGrade] = useState<GradedAttempt | null>(null);
  const [gradingFailed, setGradingFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A grading allowance can run out part-way through a set, so this is a state the runner has
  // to handle, not one the start form can prevent.
  const [paywall, setPaywall] = useState<PaywallDetail | null>(null);
  // Set in an effect rather than at render: reading the clock during render is impure, and
  // the value only ever feeds telemetry on the next submission.
  const startedAt = useRef(0);

  const question = questions[index];
  const remaining = questions.filter((q) => !answered.has(q.id)).length;
  const isLast = index >= questions.length - 1;

  useEffect(() => {
    startedAt.current = Date.now();
  }, [index]);

  // Poll the submitted answer until it resolves. Cancelled on unmount and on moving question, so
  // a student who advances quickly does not leave a timer writing into a stale question's state.
  useEffect(() => {
    if (!attemptId || grade || gradingFailed) return;

    let polls = 0;
    let cancelled = false;
    const timer = setInterval(async () => {
      polls += 1;
      if (polls > MAX_POLLS) {
        clearInterval(timer);
        if (!cancelled) setGradingFailed(true);
        return;
      }
      try {
        const attempt = await fetchAttempt(attemptId);
        if (cancelled) return;
        if (isGraded(attempt)) {
          clearInterval(timer);
          setGrade(attempt);
        } else if (attempt.grading_status === 'failed') {
          clearInterval(timer);
          setGradingFailed(true);
        }
      } catch {
        // One failed poll is not worth surfacing; the budget above ends it if it persists.
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [attemptId, grade, gradingFailed]);

  const goTo = useCallback((next: number) => {
    setIndex(next);
    setDraft('');
    setAttemptId(null);
    setGrade(null);
    setGradingFailed(false);
    setError(null);
  }, []);

  async function handleSubmit() {
    if (!question) return;
    setError(null);
    setPaywall(null);
    setSubmitting(true);
    try {
      const attempt = await submitAnswer(session.id, {
        question_id: question.id,
        answer: draft.trim(),
        time_taken_seconds: Math.round((Date.now() - startedAt.current) / 1000),
      });
      setAnswered((current) => new Set(current).add(question.id));
      setAttemptId(attempt.id);
    } catch (caught) {
      // A grading limit is not a lost answer and must not be phrased as one: "try submitting
      // again" would be false, because submitting again is exactly what will not work.
      const limit = paywallDetail(caught);
      if (limit) {
        setPaywall(limit);
      } else {
        setError(
          caught instanceof ApiError
            ? `${caught.message} Your answer is still here — try submitting again.`
            : 'Could not save your answer. It is still here — try again.',
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleFinish() {
    setError(null);
    setFinishing(true);
    try {
      await completeSession(session.id);
      router.push(`/practice/${session.id}/summary` as Route);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not finish. Please try again.');
      setFinishing(false);
    }
  }

  if (!question) {
    return <Alert tone="error">This practice set has no questions.</Alert>;
  }

  const busy = submitting || finishing;
  const submitted = attemptId !== null;
  const canSubmit = draft.trim().length >= MIN_USEFUL_LENGTH && !busy && paywall === null;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8">
      <ProgressRail
        total={questions.length}
        questions={questions}
        answeredIds={answered}
        currentIndex={index}
        onJump={busy || submitted ? undefined : goTo}
      />

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="label-micro">
            Question {index + 1} of {questions.length} · {question.category_name}
          </p>
          <DifficultyMeter level={question.difficulty} />
        </div>
        <h1 className="mt-4 text-2xl leading-snug font-medium text-text-primary md:text-[1.75rem]">
          {question.prompt}
        </h1>
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {paywall ? (
        <PaywallNotice detail={paywall} heading="Daily grading limit" />
      ) : null}

      {!submitted ? (
        <QuestionComposer key={question.id} value={draft} onChange={setDraft} disabled={busy} />
      ) : grade ? (
        <GradePanel attempt={grade} labels={grade.concept_labels} />
      ) : (
        <GradingPending failed={gradingFailed} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border-subtle pt-6">
        <p className="text-xs text-text-muted">
          {remaining === 0
            ? 'Every question answered.'
            : `${remaining} question${remaining === 1 ? '' : 's'} left`}
        </p>

        {!submitted ? (
          <Button size="lg" loading={submitting} disabled={!canSubmit} onClick={handleSubmit}>
            Submit answer
          </Button>
        ) : isLast ? (
          <Button size="lg" loading={finishing} disabled={busy} onClick={handleFinish}>
            Finish and see summary
          </Button>
        ) : (
          <Button size="lg" disabled={busy} onClick={() => goTo(index + 1)}>
            Next question
          </Button>
        )}
      </div>
    </div>
  );
}
