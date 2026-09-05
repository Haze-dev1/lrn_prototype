/**
 * The placeholder shown while a page's data is being fetched.
 *
 * Every signed-in page renders per request and waits on the API, and without a loading boundary
 * the App Router holds the *previous* page on screen until the next one is ready — so a student
 * who taps Review sees the dashboard, unchanged, for as long as the request takes, with nothing
 * to say a navigation is in flight.
 *
 * Deliberately a shape rather than a spinner. It reserves the same layout the real page will
 * occupy, so the content does not jump when it arrives, and it stays quiet: a pulsing block is a
 * loading state, an animated logo is a performance.
 */
export function PageSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite" className="animate-pulse space-y-6">
      <span className="sr-only">Loading</span>
      <div className="space-y-3">
        <div className="h-3 w-24 rounded bg-surface-2" />
        <div className="h-9 w-72 max-w-full rounded bg-surface-2" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="h-24 rounded-[--radius-card] bg-surface-1" />
        ))}
      </div>
    </div>
  );
}
