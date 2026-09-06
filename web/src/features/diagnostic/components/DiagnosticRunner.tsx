'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useCallback, useMemo, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { MIN_USEFUL_LENGTH, QuestionComposer } from '@/features/diagnostic/components/QuestionComposer';
import { InlineGlossaryText } from '@/features/glossary/components/InlineGlossaryText';
import { DifficultyMeter } from '@/features/diagnostic/components/DifficultyMeter';
import { ProgressRail } from '@/features/diagnostic/components/ProgressRail';
import { ApiError } from '@/lib/api/client';
import { completeSession, submitAnswer, type SessionState } from '@/lib/api/sessions';

export interface DiagnosticRunnerProps {
  session: SessionState;
}

/**
 * The diagnostic sitting.
 *
 * Grades are deliberately **not** shown per question. This is an assessment, not a practice
 * drill: revealing a score after every answer would let a student calibrate mid-sitting, turn 24
 * questions into 24 emotional beats, and drain the results page of the payoff it is supposed to
 * deliver. Practice, where learning from each answer is the point, reveals grades immediately.
 *
 * Answers are submitted one at a time rather than batched at the end, so a closed tab or a lost
 * connection costs at most the question in progress. The server is the source of truth for what
 * has been answered; this component starts from the state the server returned.
 */
export function DiagnosticRunner({ session }: DiagnosticRunnerProps) {
  const router = useRouter();
  const questions = session.questions;

  const [answered, setAnswered] = useState<Set<string>>(
    () => new Set(questions.filter((q) => q.attempt_id).map((q) => q.id)),
  );
  // Resume on the first unanswered question rather than at the start.
  const [index, setIndex] = useState(() => {
    const next = questions.findIndex((q) => !q.attempt_id);
    return next === -1 ? Math.max(questions.length - 1, 0) : next;
  });
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(() => Date.now());

  const question = questions[index];
  const remaining = useMemo(
    () => questions.filter((q) => !answered.has(q.id)).length,
    [questions, answered],
  );
  const allAnswered = remaining === 0;

  const goTo = useCallback(
    (next: number) => {
      setIndex(next);
      setDraft('');
      setError(null);
      setStartedAt(Date.now());
    },
    [],
  );

  async function handleSubmit() {
    if (!question) return;
    setError(null);
    setSubmitting(true);
    try {
      await submitAnswer(session.id, {
        question_id: question.id,
        answer: draft.trim(),
        time_taken_seconds: Math.round((Date.now() - startedAt) / 1000),
      });
      const next = new Set(answered);
      next.add(question.id);
      setAnswered(next);

      const following = questions.findIndex((q) => !next.has(q.id));
      if (following === -1) {
        setDraft('');
      } else {
        goTo(following);
      }
    } catch (caught) {
      // The answer is not lost: it stays in the composer, so a retry costs a click rather than
      // retyping. This is the network-failure path a student actually hits on campus wifi.
      setError(
        caught instanceof ApiError
          ? `${caught.message} Your answer is still here — try submitting again.`
          : 'Could not save your answer. It is still here — try again.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleFinish() {
    setError(null);
    setFinishing(true);
    try {
      await completeSession(session.id);
      router.push(`/diagnostic/${session.id}/results` as Route);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not finish. Please try again.',
      );
      setFinishing(false);
    }
  }

  if (!question) {
    return <Alert tone="error">This diagnostic has no questions.</Alert>;
  }

  const busy = submitting || finishing;
  const canSubmit = draft.trim().length >= MIN_USEFUL_LENGTH && !busy;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8">
      <ProgressRail
        total={questions.length}
        answeredIds={answered}
        questions={questions}
        currentIndex={index}
        onJump={busy ? undefined : goTo}
      />

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="label-micro">
            Question {index + 1} of {questions.length} · {question.category_name}
          </p>
          <DifficultyMeter level={question.difficulty} />
        </div>

        <h1 className="mt-4 text-2xl leading-snug font-medium text-text-primary md:text-[1.75rem]">
          <InlineGlossaryText text={question.prompt} />
        </h1>
        {question.subcategory ? (
          <p className="mt-2 text-sm text-text-muted">{question.subcategory}</p>
        ) : null}
      </div>

      {error ? <Alert tone="error">{error}</Alert> : null}

      {answered.has(question.id) ? (
        <Alert tone="info">
          Answered. Your responses are graded after you finish — you will see every score together
          on the results page.
        </Alert>
      ) : (
        // Keyed on the question so moving on remounts the composer: the draft and its
        // touched state reset without an effect, and focus lands on the new question.
        <QuestionComposer
          key={question.id}
          value={draft}
          onChange={setDraft}
          disabled={busy}
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border-subtle pt-6">
        <div className="flex gap-2">
          <Button
            variant="ghost"
            disabled={index === 0 || busy}
            onClick={() => goTo(index - 1)}
          >
            Previous
          </Button>
          <Button
            variant="ghost"
            disabled={index >= questions.length - 1 || busy}
            onClick={() => goTo(index + 1)}
          >
            Skip
          </Button>
        </div>

        <div className="flex items-center gap-3">
          {allAnswered ? (
            <Button size="lg" loading={finishing} disabled={busy} onClick={handleFinish}>
              Finish and grade
            </Button>
          ) : answered.has(question.id) ? (
            <Button
              size="lg"
              disabled={busy}
              onClick={() => {
                const next = questions.findIndex((q) => !answered.has(q.id));
                if (next !== -1) goTo(next);
              }}
            >
              Next unanswered
            </Button>
          ) : (
            <Button size="lg" loading={submitting} disabled={!canSubmit} onClick={handleSubmit}>
              Submit answer
            </Button>
          )}
        </div>
      </div>

      {!allAnswered ? (
        <p className="text-center text-xs text-text-muted">
          {remaining} question{remaining === 1 ? '' : 's'} left. You can leave and come back — your
          answers are saved as you go.
        </p>
      ) : null}
    </div>
  );
}
