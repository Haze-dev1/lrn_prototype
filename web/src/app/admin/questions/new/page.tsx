import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { NewQuestionForm } from '@/features/admin/components/NewQuestionForm';
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
  return { title: 'New question' };
}

export default async function NewQuestionPage() {
  const user = await requireAdmin('/admin/questions/new');
  const categories = await fetchCategories();

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/admin/questions">
      <main className="mx-auto w-full max-w-2xl space-y-6 px-6 py-12">
        <div>
          <Link
            href={'/admin/questions' as Route}
            className="label-micro hover:text-text-secondary"
          >
            ← Question bank
          </Link>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-text-primary">
            New question
          </h1>
        </div>

        <NewQuestionForm categories={categories} />
      </main>
    </AppShell>
  );
}
