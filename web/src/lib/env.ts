/**
 * Environment access for the web application.
 *
 * Server-only values are read through `serverEnv` and must never be imported into a Client
 * Component; only `NEXT_PUBLIC_`-prefixed values are safe to reach the browser bundle.
 */

/** Base URL the server uses to reach the API over the container network. */
export const serverEnv = {
  apiBaseUrl: process.env.API_BASE_URL ?? 'http://api:8000',
} as const;

/** Values that are safe to expose in the browser bundle. */
export const publicEnv = {
  /**
   * Same-origin API path. The reverse proxy routes it to the API container, which is why the
   * browser never needs a cross-origin URL and the session cookie can stay SameSite=Lax.
   */
  apiPath: process.env.NEXT_PUBLIC_API_PATH ?? '/api',
} as const;
