import type { Metadata } from 'next';
import type { Route } from 'next';
import Link from 'next/link';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';
import { CoveragePanel } from '@/features/admin/components/CoveragePanel';
import { QuestionFilters } from '@/features/admin/components/QuestionFilters';
import { QuestionTable } from '@/features/admin/components/QuestionTable';
import { listQuestions, type QuestionFilters as Filters } from '@/lib/api/admin';
import { fetchCoverage } from '@/lib/api/admin';
import { fetchCategories } from '@/lib/api/questions';
import { requireAdmin } from '@/lib/auth/session';

// Depends on the caller's session and on live bank state, so it is rendered per request.
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
  return { title: 'Question bank' };
}

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

/** Read one search parameter as a string, ignoring repeated values. */
function one(params: Record<string, string | string[] | undefined>, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

export default async function QuestionBankPage({ searchParams }: PageProps) {
  const user = await requireAdmin('/admin/questions');
  const params = await searchParams;

  const difficulty = Number(one(params, 'difficulty'));
  const filters: Filters = {
    category_slug: one(params, 'category_slug'),
    status: one(params, 'status') as Filters['status'],
    // A non-numeric difficulty in the URL is dropped rather than sent, so a hand-edited query
    // string produces an unfiltered list instead of a validation error page.
    difficulty: Number.isInteger(difficulty) && difficulty >= 1 && difficulty <= 5
      ? difficulty
      : undefined,
    search: one(params, 'search'),
    before: one(params, 'before'),
    limit: 50,
  };

  const [categories, coverage, page] = await Promise.all([
    fetchCategories(),
    fetchCoverage(),
    listQuestions(filters),
  ]);

  const nextQuery = new URLSearchParams(
    Object.entries(params).flatMap(([key, value]) =>
      typeof value === 'string' && key !== 'before' ? [[key, value] as [string, string]] : [],
    ),
  );
  if (page.next_cursor) nextQuery.set('before', page.next_cursor);

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/admin/questions">
      <main className="mx-auto w-full max-w-5xl space-y-6 px-6 py-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="label-micro">Admin</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
              Question bank
            </h1>
          </div>
          <Link href={'/admin/questions/new' as Route}>
            <Button size="md">New question</Button>
          </Link>
        </div>

        <CoveragePanel coverage={coverage} />

        <QuestionFilters categories={categories} />

        <QuestionTable questions={page.items} categories={categories} />

        {page.next_cursor ? (
          <div className="flex justify-center">
            <Link
              href={`/admin/questions?${nextQuery.toString()}` as Route}
              className="text-sm text-accent underline-offset-4 hover:underline"
            >
              Next page
            </Link>
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}
