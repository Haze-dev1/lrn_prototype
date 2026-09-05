/**
 * Central typed API client.
 *
 * Every backend call goes through here so authentication, error normalisation and timeouts are
 * defined once. Components never call `fetch` directly, and never see a raw provider error.
 */

import { publicEnv, serverEnv } from '@/lib/env';

/** A backend failure normalised into something safe to render. */
export class ApiError extends Error {
  readonly status: number;

  /**
   * The response's `detail` payload when it was structured rather than a plain string.
   *
   * Some endpoints answer with a machine-readable body — rubric validation returns the full list
   * of what is wrong — and flattening that into a single sentence would throw away exactly the
   * part the user needs to act on. Always `unknown`: callers must narrow it before rendering, so
   * an unexpected shape cannot reach the DOM.
   */
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  /** JSON-serialisable request body. */
  body?: unknown;
  /** Abort the request after this many milliseconds. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 15_000;

const isServer = typeof window === 'undefined';

/**
 * Resolve the correct API base for the current execution context.
 *
 * Server Components reach the API directly over the container network; the browser goes through
 * the same-origin proxy path.
 */
function resolveBaseUrl(): string {
  return isServer ? serverEnv.apiBaseUrl : publicEnv.apiPath;
}

/**
 * Forward the caller's session cookies when running on the server.
 *
 * The browser attaches cookies automatically, but a Server Component fetch is a fresh outbound
 * request with no cookie jar. Without this, every server-rendered page would appear signed out.
 * Imported dynamically so this module stays usable from Client Components, where `next/headers`
 * does not exist.
 */
async function serverCookieHeader(): Promise<Record<string, string>> {
  if (!isServer) return {};
  const { cookies } = await import('next/headers');
  const jar = await cookies();
  const header = jar.toString();
  return header ? { Cookie: header } : {};
}

/**
 * Extract a displayable message, and any structured detail, from an error response.
 *
 * Falls back to the status text when the body is not the expected JSON shape, so a proxy error
 * page or an empty body cannot surface as "undefined" in the UI. A `detail` that is an object
 * rather than a string is carried through untouched: endpoints such as rubric validation answer
 * with a list of what is wrong, and the caller needs the list, not a summary of it.
 */
async function readError(response: Response): Promise<{ message: string; detail?: unknown }> {
  const fallback = response.statusText || 'Request failed';
  try {
    const payload: unknown = await response.json();
    if (typeof payload !== 'object' || payload === null || !('detail' in payload)) {
      return { message: fallback };
    }

    const detail: unknown = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return { message: detail, detail };
    }
    if (
      typeof detail === 'object' &&
      detail !== null &&
      'message' in detail &&
      typeof (detail as { message: unknown }).message === 'string'
    ) {
      return { message: (detail as { message: string }).message, detail };
    }
    return { message: fallback, detail };
  } catch {
    // Body was absent or not JSON; the status text is the best available signal.
    return { message: fallback };
  }
}

/**
 * Perform a typed JSON request against the backend API.
 *
 * Always sends credentials so the session cookie travels with the request, and always applies a
 * timeout so a stalled upstream cannot hold a page render open indefinitely.
 *
 * @throws {ApiError} When the response status is not in the 2xx range, or the request times out.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...rest } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${resolveBaseUrl()}${path}`, {
      ...rest,
      signal: controller.signal,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(await serverCookieHeader()),
        ...headers,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });

    if (!response.ok) {
      const { message, detail } = await readError(response);
      throw new ApiError(response.status, message, detail);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(504, 'The request timed out.');
    }
    throw new ApiError(503, 'Could not reach the server.');
  } finally {
    clearTimeout(timeout);
  }
}
