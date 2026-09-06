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
import { ChevronRight, Send, CheckCircle2 } from 'lucide-react';
import { InlineGlossaryText } from '@/features/glossary/components/InlineGlossaryText';

const POLL_INTERVAL_MS = 1000;
const MAX_POLLS = 30;
const QUESTION_SECONDS = 300;

export interface PracticeRunnerProps {
  session: SessionState;
}

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
  const [paywall, setPaywall] = useState<PaywallDetail | null>(null);
  const startedAt = useRef(0);

  const question = questions[index];
  const remaining = questions.filter((q) => !answered.has(q.id)).length;
  const isLast = index >= questions.length - 1;

  const [timeLeft, setTimeLeft] = useState(QUESTION_SECONDS);
  const [expired, setExpired] = useState(false);

  // The clock is the source of truth for how long this question has been open; the countdown
  // below derives its display from it rather than decrementing independently.
  useEffect(() => {
    startedAt.current = Date.now();
  }, [index]);

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
        // One failed poll is not worth surfacing
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [attemptId, grade, gradingFailed]);

  const goTo = useCallback((next: number) => {
    setIndex(next);
    setTimeLeft(QUESTION_SECONDS);
    setExpired(false);
    setDraft('');
    setAttemptId(null);
    setGrade(null);
    setGradingFailed(false);
    setError(null);
  }, []);

  async function handleSubmit(forcedDraft?: string) {
    if (!question) return;
    const textToSubmit = forcedDraft !== undefined ? forcedDraft : draft;
    setError(null);
    setPaywall(null);
    setSubmitting(true);
    try {
      const attempt = await submitAnswer(session.id, {
        question_id: question.id,
        answer: textToSubmit.trim(),
        time_taken_seconds: Math.round((Date.now() - startedAt.current) / 1000),
      });
      setAnswered((current) => new Set(current).add(question.id));
      setAttemptId(attempt.id);
    } catch (caught) {
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

  // The countdown reads what it needs at tick time, so a keystroke does not restart the interval.
  const latest = useRef({ draft, handleSubmit });
  useEffect(() => {
    latest.current = { draft, handleSubmit };
  });

  // One effect owns both the display and expiry. The tick derives the remaining time from the
  // clock rather than decrementing, so a backgrounded tab cannot bank extra seconds, and it
  // submits from the interval callback rather than from an effect body.
  useEffect(() => {
    if (attemptId || submitting || finishing || expired) return;

    const timer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt.current) / 1000);
      const secondsLeft = Math.max(0, QUESTION_SECONDS - elapsed);
      setTimeLeft(secondsLeft);
      if (secondsLeft > 0) return;

      clearInterval(timer);
      setExpired(true);
      const { draft: current, handleSubmit: submit } = latest.current;
      const finalDraft =
        current.trim().length < MIN_USEFUL_LENGTH
          ? `${current} [Time expired]`.padEnd(MIN_USEFUL_LENGTH, '.')
          : current;
      setDraft(finalDraft);
      void submit(finalDraft);
    }, 1000);

    return () => clearInterval(timer);
  }, [attemptId, submitting, finishing, expired]);

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
  const awaitingGrade = submitted && !grade && !gradingFailed;
  const canSubmit = draft.trim().length >= MIN_USEFUL_LENGTH && !busy && paywall === null;
  const minutes = Math.floor(timeLeft / 60);
  const seconds = timeLeft % 60;
  const timerUrgent = timeLeft > 0 && timeLeft <= 60;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-12 animate-in fade-in duration-700 pb-20">
      
      <div className="px-2 border-b border-border-subtle pb-6 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="label-micro text-accent">PRACTICE ENVIRONMENT</span>
          <ProgressRail
            total={questions.length}
            questions={questions}
            answeredIds={answered}
            currentIndex={index}
            onJump={busy || submitted ? undefined : goTo}
          />
        </div>
        
        {/* Timer */}
        {!submitted && (
          <div className={`flex items-center gap-2 tabular-nums font-mono font-medium border px-4 py-1.5 rounded-full ${timerUrgent ? 'border-band-needs-work text-band-needs-work animate-pulse' : 'border-border-strong text-text-primary bg-surface-1'}`}>
            <span className="text-xs uppercase tracking-wider mr-1 opacity-70">TIME</span>
            {minutes}:{seconds.toString().padStart(2, '0')}
          </div>
        )}
      </div>

      <div className="px-2">
        <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center justify-center w-8 h-8 rounded-full bg-surface-2 text-text-primary font-mono text-sm font-semibold border border-border-strong">
              {index + 1}
            </span>
            <span className="label-micro text-text-secondary">{question.category_name}</span>
          </div>
          <DifficultyMeter level={question.difficulty} />
        </header>

        <h1 className="text-2xl md:text-3xl leading-relaxed font-light text-text-primary mb-12 tracking-tight">
          <InlineGlossaryText text={question.prompt} />
        </h1>

        {error ? <Alert tone="error" className="mb-8">{error}</Alert> : null}
        {paywall ? (
          <div className="mb-8"><PaywallNotice detail={paywall} heading="Daily grading limit" /></div>
        ) : null}

        <div className="relative mt-8">
          {!submitted ? (
            <QuestionComposer key={question.id} value={draft} onChange={setDraft} disabled={busy} />
          ) : grade ? (
            <GradePanel attempt={grade} labels={grade.concept_labels} />
          ) : (
            <GradingPending failed={gradingFailed} />
          )}
        </div>
      </div>

      <footer className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8 px-2 border-t border-border-subtle">
        <div className="flex items-center gap-2">
          {remaining === 0 ? (
            <span className="flex items-center gap-2 text-sm font-medium text-band-strong">
              <CheckCircle2 className="w-4 h-4" /> All answered
            </span>
          ) : (
            <span className="text-sm font-medium text-text-muted">
              {remaining} question{remaining === 1 ? '' : 's'} remaining
            </span>
          )}
        </div>

        <div className="w-full sm:w-auto">
          {!submitted ? (
            <Button 
              size="lg" 
              loading={submitting} 
              disabled={!canSubmit} 
              onClick={() => handleSubmit()}
              className="w-full sm:w-auto bg-text-primary text-canvas hover:bg-text-secondary rounded-full px-8 shadow-sm"
            >
              Submit answer
              {!submitting && <Send className="w-4 h-4 ml-2" />}
            </Button>
          ) : isLast ? (
            <Button 
              size="lg" 
              loading={finishing} 
              disabled={busy} 
              onClick={handleFinish}
              className="w-full sm:w-auto bg-text-primary text-canvas hover:bg-text-secondary rounded-full px-8 shadow-sm group"
            >
              Finish and see summary
              {!finishing && <CheckCircle2 className="w-4 h-4 ml-2" />}
            </Button>
          ) : (
            <Button 
              size="lg" 
              disabled={busy || awaitingGrade} 
              onClick={() => goTo(index + 1)}
              className="w-full sm:w-auto bg-text-primary text-canvas hover:bg-text-secondary rounded-full px-8 shadow-sm group"
            >
              {awaitingGrade ? 'Grading…' : 'Next question'}
              <ChevronRight className="w-4 h-4 ml-1 transition-transform group-hover:translate-x-1" />
            </Button>
          )}
        </div>
      </footer>
    </div>
  );
}
