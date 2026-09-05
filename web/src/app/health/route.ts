/**
 * Container liveness endpoint for the web service.
 *
 * Deliberately performs no upstream I/O: a slow API must not cause the web container to be
 * restarted by its health check.
 */
export const dynamic = 'force-dynamic';

export function GET() {
  return Response.json({ status: 'alive' });
}
