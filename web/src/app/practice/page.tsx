import type { Metadata } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { StartPracticeForm } from '@/features/practice/components/StartPracticeForm';
import { fetchEntitlement } from '@/lib/api/billing';
import { fetchCategories } from '@/lib/api/questions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Practice' };

interface PageProps {
  searchParams: Promise<{ category?: string }>;
}

export default async function PracticePage({ searchParams }: PageProps) {
  const user = await requireOnboardedUser('/practice');
  const { category } = await searchParams;
  const [categories, entitlement] = await Promise.all([fetchCategories(), fetchEntitlement()]);

  // A category from the query string is a convenience, not a trust boundary: the API validates it
  // and returns 400 for anything it does not recognise.
  const preselected = categories.some((item) => item.slug === category) ? category : null;

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/practice">
      <main className="mx-auto w-full max-w-2xl space-y-8 px-6 py-12">
        <div>
          <p className="label-micro">Practice</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            Work on what is actually weak
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Questions are chosen from your weakest categories, anything you previously missed that
            is due for review, and material you have not seen yet. You will see each score as you
            go.
          </p>
        </div>

        <StartPracticeForm
          categories={categories}
          initialCategory={preselected}
          entitlement={entitlement}
        />
      </main>
    </AppShell>
  );
}
