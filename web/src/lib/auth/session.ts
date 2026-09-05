/**
 * Server-side session helpers.
 *
 * Every gate here is a redirect for user experience, never the security boundary: the API
 * re-checks authentication and ownership on every request, so a client that skips these still
 * gets nothing.
 */

import type { Route } from 'next';
import { notFound, redirect } from 'next/navigation';
import { cache } from 'react';

import { ApiError } from '@/lib/api/client';
import { fetchCurrentUser, type CurrentUser } from '@/lib/api/auth';

/**
 * Return the signed-in user, or null when the request carries no valid session.
 *
 * Swallows only authentication failures — a network or server error is rethrown, so an outage
 * surfaces as an error rather than silently rendering the page as signed out.
 *
 * Memoised per request with React's `cache`, because a page that gates in both
 * `generateMetadata` and its component would otherwise authenticate twice. The identity fetch is
 * `no-store`, so Next's own fetch deduplication does not apply.
 */
export const getCurrentUser = cache(async (): Promise<CurrentUser | null> => {
  try {
    return await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      return null;
    }
    throw error;
  }
});

/** Require a signed-in user, redirecting to sign-in and preserving the intended destination. */
export async function requireUser(returnTo?: string): Promise<CurrentUser> {
  const user = await getCurrentUser();
  if (!user) {
    // Built at runtime, so it cannot be checked against the static route map; the literal
    // prefix is a known route and only the query string varies.
    const target = (
      returnTo ? `/signin?next=${encodeURIComponent(returnTo)}` : '/signin'
    ) as Route;
    redirect(target);
  }
  return user;
}

/** Require a user who has finished onboarding, sending them to onboarding if they have not. */
export async function requireOnboardedUser(returnTo?: string): Promise<CurrentUser> {
  const user = await requireUser(returnTo);
  if (!user.onboarding_complete) {
    redirect('/onboarding');
  }
  return user;
}

/**
 * Require an administrator, rendering the not-found page for anyone else.
 *
 * Mirrors the API, which answers 404 rather than 403 on admin routes so their existence is not
 * confirmed to an ordinary account. A 403-style "you do not have access" page here would leak
 * exactly what the API is careful not to.
 */
export async function requireAdmin(returnTo?: string): Promise<CurrentUser> {
  const user = await requireUser(returnTo);
  if (!user.is_admin) {
    notFound();
  }
  return user;
}
