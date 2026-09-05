import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';
import { notFound } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { LifecycleControl } from '@/features/admin/components/LifecycleControl';
import { TaxonomyForm } from '@/features/admin/components/TaxonomyForm';
import { VersionEditor } from '@/features/admin/components/VersionEditor';
import { VersionHistory } from '@/features/admin/components/VersionHistory';
import { fetchQuestion, fetchVersion, type QuestionVersion } from '@/lib/api/admin';
import { ApiError } from '@/lib/api/client';
import { fetchCategories } from '@/lib/api/questions';
import { requireAdmin } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

/**
 * Generated rather than static, so the admin gate runs before any metadata is produced.
 *
 * A static `metadata` export is rendered into the streamed payload even when the component then
 * calls `notFound()`, which would confirm to an ordinary account that this route exists and what
 * it is called — exactly what the API's 404-instead-of-403 answer is careful not to say.
 */
export async function generateMetadata(): Promise<Metadata> {
  await requireAdmin();
  return { title: 'Question' };
}

interface PageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ version?: string }>;
}

export default async function QuestionDetailPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { version: requestedVersion } = await searchParams;
  const user = await requireAdmin(`/admin/questions/${id}`);

  const [categories, question] = await Promise.all([
    fetchCategories(),
    fetchQuestion(id).catch((error: unknown) => {
      // A question that does not exist, and one whose ID was mistyped, are the same 404 here as
      // they are at the API. Anything else is a real failure and is left to the error boundary.
      if (error instanceof ApiError && error.status === 404) notFound();
      throw error;
    }),
  ]);

  // Content is fetched only for the version actually being opened, one at a time, rather than
  // shipping every rubric in the history to the browser.
  let version: QuestionVersion | null = null;
  if (requestedVersion) {
    version = await fetchVersion(id, requestedVersion).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) notFound();
      throw error;
    });
  }

  const categoryName =
    categories.find((category) => category.slug === question.category_slug)?.name ??
    question.category_slug;

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/admin/questions">
      <main className="mx-auto w-full max-w-6xl space-y-6 px-6 py-12">
        <div>
          <Link
            href={'/admin/questions' as Route}
            className="label-micro hover:text-text-secondary"
          >
            ← Question bank
          </Link>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-text-primary">
            {categoryName}
          </h1>
          <p className="mt-2 text-sm text-text-secondary">
            {question.subcategory ? `${question.subcategory} · ` : ''}
            Level {question.difficulty}
            {question.source_key ? (
              <>
                {' · '}
                <span className="font-mono text-xs text-text-muted">{question.source_key}</span>
              </>
            ) : null}
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
          <div className="min-w-0 space-y-6 lg:order-1">
            {/* Keyed by version so React remounts the editor when the selection changes.
                The editor seeds its form state from the version prop in a useState initialiser,
                which does not re-run on a client-side navigation between two versions of the
                same question — without the key, switching versions shows the previous version's
                content, or an empty form. */}
            <VersionEditor
              key={version?.id ?? 'new'}
              questionId={question.id}
              version={version}
            />
          </div>

          <div className="space-y-6 lg:order-2">
            <LifecycleControl
              questionId={question.id}
              status={question.status}
              hasPublishedVersion={question.published_version !== null}
            />
            <VersionHistory
              questionId={question.id}
              versions={question.versions}
              selectedId={version?.id ?? null}
            />
            {/* Keyed for the same reason: navigating between two questions reuses this
                component, and its fields are seeded from props exactly once. */}
            <TaxonomyForm key={question.id} question={question} categories={categories} />
          </div>
        </div>
      </main>
    </AppShell>
  );
}
