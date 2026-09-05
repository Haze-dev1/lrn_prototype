/**
 * Google sign-in.
 *
 * Two things are worth pinning here, and neither is "the button renders".
 *
 * The first is the redirect guard. `?next=` is attacker-controlled, and a sign-in method that
 * honours it without checking turns a genuine LRN sign-in page into a phishing hop. Password
 * sign-in already guarded this; the guard is now shared, and these tests are what stop the two
 * methods drifting apart again.
 *
 * The second is that the credential never becomes client state. It is handed to the API and
 * forgotten — the session is the API's HttpOnly cookie pair, exactly as it is for a password.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GoogleSignInButton } from '@/features/auth/components/GoogleSignInButton';
import type { CurrentUser } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';
import { destinationAfterSignIn, safeNextPath } from '@/lib/auth/redirect';

const replace = vi.fn();
const refresh = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, refresh }),
}));

// next/script does not load anything in jsdom, so it is reduced to firing onReady. That is the
// only part of its behaviour this component depends on.
vi.mock('next/script', () => ({
  default: ({ onReady }: { onReady?: () => void }) => {
    onReady?.();
    return null;
  },
}));

const signInWithGoogle = vi.fn();
vi.mock('@/lib/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/auth')>();
  return { ...actual, signInWithGoogle: (...args: unknown[]) => signInWithGoogle(...args) };
});

const CLIENT_ID = 'test-client-id.apps.googleusercontent.com';

function user(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: 'u1',
    email: 'student@example.com',
    is_admin: false,
    email_verified: true,
    onboarding_complete: true,
    profile: null,
    ...overrides,
  };
}

/** Captures what the component passes to Google, and lets a test play the callback back. */
function installGoogleStub() {
  const captured: {
    clientId?: string;
    uxMode?: string;
    autoSelect?: boolean;
    buttonOptions?: Record<string, unknown>;
    fire?: (response: { credential?: string }) => void;
  } = {};

  window.google = {
    accounts: {
      id: {
        initialize(config) {
          captured.clientId = config.client_id;
          captured.uxMode = config.ux_mode;
          captured.autoSelect = config.auto_select;
          captured.fire = config.callback;
        },
        renderButton(_parent, options) {
          captured.buttonOptions = options;
        },
      },
    },
  };
  return captured;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  delete window.google;
});

describe('safeNextPath', () => {
  it('honours a same-origin path', () => {
    expect(safeNextPath('/progress')).toBe('/progress');
  });

  it.each([
    ['a protocol-relative URL', '//evil.example/login'],
    ['a backslash-prefixed URL some browsers normalise', '/\\evil.example'],
    ['an absolute http URL', 'http://evil.example'],
    ['an absolute https URL', 'https://evil.example'],
    ['a scheme-only value', 'javascript:alert(1)'],
    ['a bare path with no leading slash', 'evil.example'],
  ])('rejects %s', (_label, value) => {
    expect(safeNextPath(value)).toBeNull();
  });

  it('rejects an empty or missing value', () => {
    expect(safeNextPath('')).toBeNull();
    expect(safeNextPath(null)).toBeNull();
    expect(safeNextPath(undefined)).toBeNull();
  });
});

describe('destinationAfterSignIn', () => {
  it('sends an onboarded user to their requested page', () => {
    expect(destinationAfterSignIn(true, '/review')).toBe('/review');
  });

  it('falls back to the dashboard when there is no next path', () => {
    expect(destinationAfterSignIn(true, undefined)).toBe('/dashboard');
  });

  it('falls back to the dashboard rather than an off-site next path', () => {
    expect(destinationAfterSignIn(true, '//evil.example')).toBe('/dashboard');
  });

  it('sends an un-onboarded user to onboarding even with a next path', () => {
    // Every gated page assumes a completed profile, so honouring next here would bounce them
    // straight back to the sign-in page they just left.
    expect(destinationAfterSignIn(false, '/review')).toBe('/onboarding');
  });
});

describe('GoogleSignInButton', () => {
  it('initialises Google with the client ID the server supplied', async () => {
    const google = installGoogleStub();
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.clientId).toBe(CLIENT_ID));
  });

  it('uses the popup flow and does not sign a returning user in unasked', async () => {
    const google = installGoogleStub();
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.uxMode).toBe('popup'));
    expect(google.autoSelect).toBe(false);
  });

  it('lets Google render its own button rather than drawing one', async () => {
    const google = installGoogleStub();
    render(<GoogleSignInButton clientId={CLIENT_ID} text="signup_with" />);

    await waitFor(() => expect(google.buttonOptions).toBeDefined());
    expect(google.buttonOptions).toMatchObject({ type: 'standard', text: 'signup_with' });
  });

  it('exchanges the credential for a session and lands on the dashboard', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockResolvedValue(user());
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    await waitFor(() => expect(signInWithGoogle).toHaveBeenCalledWith('google-id-token'));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(refresh).toHaveBeenCalled();
  });

  it('sends a user who has not onboarded to onboarding', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockResolvedValue(user({ onboarding_complete: false }));
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
  });

  it('honours a same-origin next path', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockResolvedValue(user());
    render(<GoogleSignInButton clientId={CLIENT_ID} nextPath="/progress" />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/progress'));
  });

  it('refuses to redirect off-site after signing in', async () => {
    // The whole point of the shared guard: Google sign-in must not be an open redirect that
    // password sign-in is not.
    const google = installGoogleStub();
    signInWithGoogle.mockResolvedValue(user());
    render(<GoogleSignInButton clientId={CLIENT_ID} nextPath="//evil.example" />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
    expect(replace).not.toHaveBeenCalledWith('//evil.example');
  });

  it('never stores the credential in browser storage', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockResolvedValue(user());
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('explains a dismissed popup without claiming a failure', async () => {
    const google = installGoogleStub();
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({});

    expect(await screen.findByText(/was not completed/i)).toBeInTheDocument();
    expect(signInWithGoogle).not.toHaveBeenCalled();
  });

  it('reports a rejected Google token without redirecting', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockRejectedValue(new ApiError(401, 'Could not verify Google sign-in'));
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'bad-token' });

    expect(await screen.findByText(/could not verify that Google account/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it('points a user at password sign-in when Google is unconfigured server-side', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockRejectedValue(new ApiError(503, 'Google sign-in is not available'));
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    expect(await screen.findByText(/use your email and password/i)).toBeInTheDocument();
  });

  it('never renders a raw API error message', async () => {
    const google = installGoogleStub();
    signInWithGoogle.mockRejectedValue(new Error('psycopg: connection refused at 10.0.0.4:5432'));
    render(<GoogleSignInButton clientId={CLIENT_ID} />);

    await waitFor(() => expect(google.fire).toBeDefined());
    google.fire!({ credential: 'google-id-token' });

    expect(await screen.findByText(/could not sign you in with Google/i)).toBeInTheDocument();
    expect(screen.queryByText(/psycopg/i)).not.toBeInTheDocument();
  });
});
