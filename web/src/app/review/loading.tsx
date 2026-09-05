import { PageSkeleton } from '@/components/layout/PageSkeleton';

/** Shown while the review page's data is fetched. See `PageSkeleton`. */
export default function Loading() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <PageSkeleton />
    </main>
  );
}
