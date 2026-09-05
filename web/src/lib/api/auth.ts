/** Typed API client functions for authentication and account management. */

import { apiRequest } from '@/lib/api/client';

export type TargetRole = 'ib' | 'pe' | 'both';

export interface Profile {
  school: string | null;
  graduation_year: number | null;
  target_role: TargetRole | null;
  recruiting_consent: boolean;
  recruiting_consent_updated_at: string | null;
  marketing_emails_opt_in: boolean;
  onboarding_completed_at: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  is_admin: boolean;
  email_verified: boolean;
  onboarding_complete: boolean;
  profile: Profile | null;
}

export interface DataExport {
  exported_at: string;
  account: Record<string, unknown>;
  profile: Record<string, unknown> | null;
  sessions: Record<string, unknown>[];
  attempts: Record<string, unknown>[];
  skill_scores: Record<string, unknown>[];
  grade_flags: Record<string, unknown>[];
}

export interface AuthConfig {
  /** Whether this deployment can verify Google tokens. */
  google_enabled: boolean;
  /** Public Google Web Application client ID, or null when Google sign-in is off. */
  google_client_id: string | null;
}

/**
 * Read which sign-in methods this deployment offers.
 *
 * Served by the API rather than baked into the bundle as a `NEXT_PUBLIC_` value, so the client ID
 * the browser signs in with is always the one the API verifies against, and changing it does not
 * require rebuilding the web image.
 */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  return apiRequest<AuthConfig>('/v1/auth/config', { cache: 'no-store' });
}

/**
 * Exchange a Google ID token for an LRN session.
 *
 * The token is verified server-side against Google's published keys. It is passed straight
 * through and never stored: the session the API sets is the same HttpOnly cookie pair password
 * sign-in produces, so there is no second session mechanism to secure.
 */
export async function signInWithGoogle(idToken: string): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/auth/google', {
    method: 'POST',
    body: { id_token: idToken },
  });
}

/** Create an account and start a session. */
export async function register(email: string, password: string): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/auth/register', {
    method: 'POST',
    body: { email, password },
  });
}

/** Sign in with an email address and password. */
export async function login(email: string, password: string): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/auth/login', {
    method: 'POST',
    body: { email, password },
  });
}

/** End the current session. */
export async function logout(): Promise<void> {
  await apiRequest<{ message: string }>('/v1/auth/logout', { method: 'POST' });
}

/** Fetch the signed-in user. Never cached: a stale identity is a security problem. */
export async function fetchCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/auth/me', { cache: 'no-store' });
}

/** Save onboarding answers. */
export async function completeOnboarding(input: {
  school: string;
  graduation_year: number;
  target_role: TargetRole;
}): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/onboarding', { method: 'POST', body: input });
}

/** Update editable profile fields. */
export async function updateProfile(input: {
  school?: string;
  graduation_year?: number;
  target_role?: TargetRole;
}): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/profile', { method: 'PATCH', body: input });
}

/** Grant or withdraw recruiting consent. Separate from profile updates by design. */
export async function setRecruitingConsent(granted: boolean): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/v1/account/recruiting-consent', {
    method: 'PUT',
    body: { recruiting_consent: granted },
  });
}

/** Download everything the account holds. */
export async function exportData(): Promise<DataExport> {
  return apiRequest<DataExport>('/v1/account/export', { cache: 'no-store' });
}

/** Permanently delete the account. Irreversible. */
export async function deleteAccount(password: string | null): Promise<void> {
  await apiRequest<{ message: string }>('/v1/account/delete', {
    method: 'POST',
    body: { confirmation: 'DELETE', password },
  });
}

export interface EmailPreferences {
  /** Weekly weak-area reminders. On by default; refusable without signing in. */
  study_reminder_emails: boolean;
  /** Product news. Off unless explicitly turned on. */
  marketing_emails_opt_in: boolean;
}

/** Read the caller's own email preferences. */
export async function fetchEmailPreferences(): Promise<EmailPreferences> {
  return apiRequest<EmailPreferences>('/v1/account/email-preferences');
}

/** Update the caller's own email preferences. */
export async function setEmailPreferences(
  preferences: EmailPreferences,
): Promise<EmailPreferences> {
  return apiRequest<EmailPreferences>('/v1/account/email-preferences', {
    method: 'PUT',
    body: preferences,
  });
}

/**
 * Turn study reminders off from an emailed link, with no session.
 *
 * A POST rather than a GET even though the email carries a URL: mail scanners fetch every link in
 * a message, and an unsubscribe that happened on GET would unsubscribe people who never clicked.
 */
export async function unsubscribeWithToken(token: string): Promise<{ message: string }> {
  return apiRequest<{ message: string }>('/v1/emails/unsubscribe', {
    method: 'POST',
    body: { token },
  });
}
