'use client';

import { useSyncExternalStore } from 'react';

import { useTheme } from '@/components/layout/ThemeProvider';

const subscribeToNothing = () => () => {};

const DARK_QUERY = '(prefers-color-scheme: dark)';

function subscribeToColorScheme(onChange: () => void) {
  const query = window.matchMedia(DARK_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/**
 * Whether the client has hydrated.
 *
 * `useSyncExternalStore` rather than a `setState` in an effect: it returns the server snapshot
 * during SSR and the client snapshot afterwards without a cascading render, which is also what
 * the `react-hooks/set-state-in-effect` rule asks for.
 */
export function useIsHydrated(): boolean {
  return useSyncExternalStore(
    subscribeToNothing,
    () => true,
    () => false
  );
}

/**
 * The theme actually in effect, with `system` resolved against the OS preference.
 *
 * Returns `null` until hydration, because the server cannot know which one applies. Callers
 * render a neutral placeholder for that first paint rather than guessing and flipping.
 */
export function useResolvedTheme(): 'dark' | 'light' | null {
  const { theme } = useTheme();
  const hydrated = useIsHydrated();
  const systemIsDark = useSyncExternalStore(
    subscribeToColorScheme,
    () => window.matchMedia(DARK_QUERY).matches,
    () => false
  );

  if (!hydrated) {
    return null;
  }
  return theme === 'system' ? (systemIsDark ? 'dark' : 'light') : theme;
}
