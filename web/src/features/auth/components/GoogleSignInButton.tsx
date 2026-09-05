'use client';

import { useRouter } from 'next/navigation';
import Script from 'next/script';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { signInWithGoogle } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';
import { destinationAfterSignIn } from '@/lib/auth/redirect';

/** Google Identity Services client library. Google requires it to be loaded from their origin. */
const GIS_SRC = 'https://accounts.google.com/gsi/client';

/** The parts of Google Identity Services this component uses, and nothing more. */
interface GoogleIdentityServices {
  accounts: {
    id: {
      initialize(config: {
        client_id: string;
        callback: (response: { credential?: string }) => void;
        ux_mode?: 'popup' | 'redirect';
        auto_select?: boolean;
      }): void;
      renderButton(
        parent: HTMLElement,
        options: {
          type?: 'standard' | 'icon';
          theme?: 'outline' | 'filled_blue' | 'filled_black';
          size?: 'small' | 'medium' | 'large';
          text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
          shape?: 'rectangular' | 'pill' | 'circle' | 'square';
          logo_alignment?: 'left' | 'center';
          width?: number;
        },
      ): void;
    };
  };
}

declare global {
  interface Window {
    google?: GoogleIdentityServices;
  }
}

export interface GoogleSignInButtonProps {
  /** Public Google Web Application client ID, supplied by the API rather than the bundle. */
  clientId: string;
  /** Raw `?next=` value from the page. Validated before it is honoured. */
  nextPath?: string;
  /** Wording on Google's own button. */
  text?: 'signin_with' | 'signup_with' | 'continue_with';
}

/**
 * Google sign-in, rendered by Google.
 *
 * The button is drawn by Google Identity Services rather than reimplemented here. That is both
 * Google's branding requirement and the reason the flow is trustworthy: the user types their
 * Google password into a Google-owned popup, never into anything this application drew.
 *
 * The credential Google returns is posted straight to the API and never stored. Nothing about the
 * Google identity is kept in the browser — the session that results is the same HttpOnly cookie
 * pair password sign-in produces, so there is no second session mechanism to secure.
 */
export function GoogleSignInButton({
  clientId,
  nextPath,
  text = 'continue_with',
}: GoogleSignInButtonProps) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const initialised = useRef(false);
  const [scriptReady, setScriptReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  const handleCredential = useCallback(
    async (response: { credential?: string }) => {
      if (!response.credential) {
        // Google resolved the flow without issuing a token — a dismissed popup, or one the
        // browser blocked. Nothing was attempted, so this is guidance rather than a failure.
        setError('Google sign-in was not completed. Please try again.');
        return;
      }

      setError(null);
      setSigningIn(true);
      try {
        const user = await signInWithGoogle(response.credential);
        router.replace(destinationAfterSignIn(user.onboarding_complete, nextPath));
        // Re-runs the Server Components so every surface sees the new session.
        router.refresh();
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          setError('We could not verify that Google account. Please try again.');
        } else if (caught instanceof ApiError && caught.status === 403) {
          setError('This account is not active. Contact support if you think that is wrong.');
        } else if (caught instanceof ApiError && caught.status === 503) {
          setError('Google sign-in is unavailable right now. Use your email and password.');
        } else {
          setError('We could not sign you in with Google. Please try again.');
        }
        setSigningIn(false);
      }
    },
    [nextPath, router],
  );

  useEffect(() => {
    if (!scriptReady || initialised.current || !containerRef.current) return;
    const gis = window.google;
    if (!gis) return;

    initialised.current = true;
    gis.accounts.id.initialize({
      client_id: clientId,
      callback: handleCredential,
      // The popup keeps the user on this page, so a `?next=` and anything already typed survive
      // a cancelled sign-in. `redirect` would discard both.
      ux_mode: 'popup',
      // Signing a returning user in without them asking is a surprise, not a convenience.
      auto_select: false,
    });
    gis.accounts.id.renderButton(containerRef.current, {
      type: 'standard',
      theme: 'filled_black',
      size: 'large',
      text,
      shape: 'rectangular',
      logo_alignment: 'left',
      width: 320,
    });
  }, [clientId, handleCredential, scriptReady, text]);

  return (
    <div className="mb-6 space-y-4">
      <Script src={GIS_SRC} strategy="afterInteractive" onReady={() => setScriptReady(true)} />

      {error ? <Alert tone="error">{error}</Alert> : null}

      <div className="flex justify-center" aria-busy={signingIn}>
        {/* Google draws into this element. It holds the button's height until the script is
            ready, so the form below does not jump when it appears. */}
        <div ref={containerRef} className="min-h-[44px]" />
      </div>

      {signingIn ? (
        <p className="text-center text-sm text-text-secondary" role="status">
          Signing you in…
        </p>
      ) : null}

      <div className="flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-border-subtle" />
        <span className="label-micro text-text-muted">or</span>
        <span className="h-px flex-1 bg-border-subtle" />
      </div>
    </div>
  );
}
