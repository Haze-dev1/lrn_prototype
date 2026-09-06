import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';
import { notFound, redirect } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';
import { GradePanel } from '@/features/practice/components/GradePanel';
import { InlineGlossaryText } from '@/features/glossary/components/InlineGlossaryText';
import { ApiError } from '@/lib/api/client';
import { fetchAttempt, isGraded } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Answer' };

interface PageProps {
  params: Promise<{ attemptId: string }>;
}

/**
 * One past answer in full.
 *
 * Shows the student's own answer above the grade, which the practice runner does not need to —
 * there the answer is still on screen and in mind. Weeks later it is the thing being reviewed,
 * and a score without the answer it refers to is not reviewable.
 *
 * "Practise this category" is the exit: review that ends in reading is a reference page, and
 * review that ends in doing is a study loop.
 */
export default async function ReviewDetailPage({ params }: PageProps) {
  const { attemptId } = await params;
  const user = await requireOnboardedUser(`/review/${attemptId}`);

  const attempt = await fetchAttempt(attemptId).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  });

  if (!isGraded(attempt)) {
    // Nothing to review until it has a grade; the list only shows graded answers, so this is a
    // hand-typed or stale URL.
    redirect('/review' as Route);
  }

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/review">
      <main className="mx-auto w-full max-w-3xl space-y-8 px-6 py-12">
        <div>
          <Link href={'/review' as Route} className="label-micro hover:text-text-secondary">
            ← Review
          </Link>
          <p className="label-micro mt-4">{attempt.category_name}</p>
          <h1 className="mt-2 text-2xl leading-snug font-medium text-text-primary">
            <InlineGlossaryText text={attempt.question_prompt} />
          </h1>
        </div>

        <section aria-labelledby="answer-heading">
          <h2 id="answer-heading" className="label-micro">
            Your answer
          </h2>
          <p className="mt-3 rounded-[--radius-card] border border-border-subtle bg-surface-1 px-5 py-4 text-sm leading-relaxed whitespace-pre-wrap text-text-secondary">
            {attempt.answer}
          </p>
        </section>

        <GradePanel attempt={attempt} labels={attempt.concept_labels} />

        <div className="flex flex-wrap items-center gap-4 border-t border-border-subtle pt-6">
          <Link href={`/practice?category=${attempt.category_slug}` as Route}>
            <Button size="lg">Practise {attempt.category_name}</Button>
          </Link>
          {attempt.concepts_missed.length > 0 ? (
            <Link
              href={`/review?missed_concept=${attempt.concepts_missed[0]}` as Route}
              className="text-sm text-accent underline-offset-4 hover:underline"
            >
              Other answers that missed this
            </Link>
          ) : null}
        </div>
      </main>
    </AppShell>
  );
}
