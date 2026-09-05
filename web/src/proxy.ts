import { NextResponse, type NextRequest } from 'next/server';

/**
 * Session refresh and route gating.
 *
 * The access cookie has a short max-age, so the browser drops it on expiry. Its absence alongside
 * a present refresh cookie is therefore a reliable "needs refresh" signal that requires no token
 * parsing here — and middleware is the only place in the request lifecycle that can both call the
 * API and set cookies on the response, which a Server Component cannot do during render.
 *
 * The redirects below are for user experience only. The API authenticates and authorises every
 * request independently, so a client that bypasses middleware entirely still gets nothing.
 */

const ACCESS_COOKIE = process.env.ACCESS_COOKIE_NAME ?? 'lrn_access';
const REFRESH_COOKIE = process.env.REFRESH_COOKIE_NAME ?? 'lrn_refresh';
const API_BASE_URL = process.env.API_BASE_URL ?? 'http://api:8000';

/**
 * Routes that require a session.
 *
 * `/pricing` is deliberately absent: a student deciding whether to start the diagnostic is
 * entitled to know what it leads to, and putting pricing behind a sign-in is a conversion
 * problem rather than a security one. `/billing` is present because the checkout return page
 * reads the caller's own entitlement.
 */
const PROTECTED_PREFIXES = [
  '/dashboard',
  '/account',
  '/onboarding',
  '/admin',
  '/billing',
  '/diagnostic',
  '/practice',
  '/review',
  '/progress',
];

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasAccess = request.cookies.has(ACCESS_COOKIE);
  const hasRefresh = request.cookies.has(REFRESH_COOKIE);
  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix));

  if (hasAccess || !hasRefresh) {
    if (isProtected && !hasAccess && !hasRefresh) {
      return redirectToSignIn(request);
    }
    return NextResponse.next();
  }

  // Access expired but a refresh token remains: rotate silently so the user is not signed out
  // mid-session every fifteen minutes.
  try {
    const refreshed = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
      method: 'POST',
      headers: { Cookie: request.headers.get('cookie') ?? '' },
    });

    if (!refreshed.ok) {
      return isProtected ? redirectToSignIn(request) : NextResponse.next();
    }

    const response = NextResponse.next();
    // Pass the API's rotated cookies straight through to the browser.
    for (const cookie of refreshed.headers.getSetCookie()) {
      response.headers.append('set-cookie', cookie);
    }
    return response;
  } catch {
    // A refresh failure must not take the page down; the API will reject the request if the
    // session really is invalid.
    return isProtected ? redirectToSignIn(request) : NextResponse.next();
  }
}

/** Redirect to sign-in, remembering where the user was heading. */
function redirectToSignIn(request: NextRequest): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = '/signin';
  url.search = `?next=${encodeURIComponent(request.nextUrl.pathname)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Static assets and the health endpoint never need a session, and running middleware on them
  // would add a refresh attempt to every image request.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|health).*)'],
};
