/**
 * Typed API client functions for plans, entitlements and hosted payment flows.
 *
 * `Entitlement` carries already-decided booleans rather than the inputs to a decision. That is
 * deliberate and mirrors the backend: a component cannot compute access differently from the
 * endpoint that enforces it, because it has nothing to compute *from*. The worst outcome in this
 * area is an interface and an API that disagree about who has paid.
 */

import { apiRequest } from '@/lib/api/client';
import { ApiError } from '@/lib/api/client';

export type PlanId = 'free' | 'pro_monthly' | 'season_pass';

export interface Plan {
  plan: PlanId;
  name: string;
  tagline: string;
  features: string[];
  /** False when the plan has no configured price. Shown as unavailable, never offered. */
  purchasable: boolean;
  /** A one-time purchase rather than a subscription. */
  one_time: boolean;
  duration_days: number | null;
}

export interface FreeTierUsage {
  diagnostics_taken: number;
  practice_sessions_used: number;
  practice_sessions_limit: number;
  practice_sessions_remaining: number;
  graded_last_24h: number;
  daily_grade_limit: number;
  grades_remaining_today: number;
}

export interface Entitlement {
  plan: PlanId;
  is_paid: boolean;
  /** Null for an active subscription, which has no end date until it is cancelled. */
  active_until: string | null;
  /** When access last ended. Drives "your access expired" rather than a first-time sales pitch. */
  expired_at: string | null;
  cancel_at_period_end: boolean;
  can_manage_billing: boolean;
  can_start_practice: boolean;
  can_grade_answer: boolean;
  can_start_new_diagnostic: boolean;
  usage: FreeTierUsage;
}

export interface PlansPayload {
  plans: Plan[];
  /** Null for an anonymous visitor: pricing is public. */
  entitlement: Entitlement | null;
  billing_enabled: boolean;
}

/** The structured body of a 402, so a paywall can explain itself rather than just sell. */
export interface PaywallDetail {
  reason:
    | 'practice_limit_reached'
    | 'grading_limit_reached'
    | 'diagnostic_limit_reached'
    | string;
  message: string;
  used: number | null;
  limit: number | null;
  upgrade_url: string;
}

/**
 * Narrow an unknown error into the structured detail a 402 carries.
 *
 * Returns null for anything else, so a component cannot mistake a network failure or a 500 for a
 * paywall and show an upgrade prompt to someone whose request simply broke.
 */
export function paywallDetail(error: unknown): PaywallDetail | null {
  if (!(error instanceof ApiError) || error.status !== 402) return null;
  const detail = error.detail;
  if (typeof detail !== 'object' || detail === null) return null;
  const candidate = detail as Partial<PaywallDetail>;
  if (typeof candidate.reason !== 'string' || typeof candidate.message !== 'string') return null;
  return {
    reason: candidate.reason,
    message: candidate.message,
    used: typeof candidate.used === 'number' ? candidate.used : null,
    limit: typeof candidate.limit === 'number' ? candidate.limit : null,
    upgrade_url: typeof candidate.upgrade_url === 'string' ? candidate.upgrade_url : '/pricing',
  };
}

/** Read the plan catalogue. Public — an anonymous caller gets a null entitlement. */
export async function fetchPlans(): Promise<PlansPayload> {
  return apiRequest<PlansPayload>('/v1/billing/plans');
}

/** Read the signed-in caller's own access and free-tier usage. */
export async function fetchEntitlement(): Promise<Entitlement> {
  return apiRequest<Entitlement>('/v1/entitlements');
}

/**
 * Read the caller's entitlement, or null when they are not signed in.
 *
 * For surfaces that render for both, where a 401 is an expected answer rather than a failure.
 */
export async function fetchEntitlementOrNull(): Promise<Entitlement | null> {
  try {
    return await fetchEntitlement();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/** Start a hosted checkout and return where to send the browser. Grants nothing by itself. */
export async function startCheckout(plan: PlanId): Promise<{ url: string }> {
  return apiRequest<{ url: string }>('/v1/billing/checkout', {
    method: 'POST',
    body: { plan },
  });
}

/** Open the provider's Customer Portal for managing or cancelling a plan. */
export async function openBillingPortal(): Promise<{ url: string }> {
  return apiRequest<{ url: string }>('/v1/billing/portal', { method: 'POST' });
}
