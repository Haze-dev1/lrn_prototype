/**
 * The two events only a browser can observe.
 *
 * Everything else in the funnel is recorded server-side, where the event is a consequence of work
 * the API actually did. This client can report a landing view and nothing that would corrupt the
 * numbers the product is measured on — the API enforces that with its own allowlist, so a
 * modified bundle gains nothing.
 *
 * Failures are swallowed. A page must never fail to render because a telemetry call did.
 */

import { apiRequest } from '@/lib/api/client';

export type PublicEvent = 'landing_view' | 'paywall_reached';

/** Report one public event, ignoring any failure. */
export async function recordEvent(event: PublicEvent): Promise<void> {
  try {
    await apiRequest<{ status: string }>('/v1/analytics/events', {
      method: 'POST',
      body: { event },
      // Short: this runs during a server render, and nobody's page should wait on analytics.
      timeoutMs: 2_000,
    });
  } catch {
    // Deliberately silent. An unrecorded landing view is a gap in a chart, not a broken page.
  }
}
