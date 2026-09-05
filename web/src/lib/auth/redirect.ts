/**
 * Post-sign-in destination handling.
 *
 * One implementation, shared by every sign-in method. A `?next=` value arrives from the URL and is
 * therefore attacker-controlled: a crafted link that lands someone on a real LRN sign-in page and
 * then bounces them elsewhere the instant they authenticate is a convincing phishing step, because
 * the part the user checked — the domain they typed their password into — was genuine. Keeping the
 * guard here rather than inline in each form is what stops one sign-in method being hardened and
 * another quietly not.
 */

import type { Route } from 'next';

/**
 * Reduce a caller-supplied `?next=` value to a same-origin path, or null.
 *
 * Accepts only a path beginning with a single `/`. A protocol-relative `//evil.example` is rejected
 * because the browser reads it as another origin, and an absolute URL is rejected outright.
 * Backslashes are rejected too: some browsers normalise `/\evil.example` into a protocol-relative
 * URL, which would defeat a check that only looked for `//`.
 */
export function safeNextPath(next: string | null | undefined): Route | null {
  if (!next) return null;
  if (!next.startsWith('/')) return null;
  if (next.startsWith('//') || next.startsWith('/\\')) return null;
  return next as Route;
}

/**
 * Decide where a freshly authenticated user should land.
 *
 * A user who has not finished onboarding always goes to onboarding, even when they arrived with a
 * `next` path: every gated page assumes a completed profile, so honouring `next` first would bounce
 * them straight back here.
 */
export function destinationAfterSignIn(onboardingComplete: boolean, next?: string | null): Route {
  if (!onboardingComplete) return '/onboarding';
  return safeNextPath(next) ?? '/dashboard';
}
