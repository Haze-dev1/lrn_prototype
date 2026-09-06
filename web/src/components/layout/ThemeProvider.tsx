'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { THEME_STORAGE_KEY, type Theme } from './theme-script';

interface ThemeProviderProps {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
}

interface ThemeProviderState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const initialState: ThemeProviderState = {
  theme: 'system',
  setTheme: () => null,
};

const ThemeProviderContext = createContext<ThemeProviderState>(initialState);

/** Read the stored preference, or fall back to the default. Safe to call during server render. */
function readStoredTheme(storageKey: string, fallback: Theme): Theme {
  if (typeof window === 'undefined') {
    return fallback;
  }
  try {
    const stored = window.localStorage.getItem(storageKey);
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : fallback;
  } catch {
    // A browser configured to block site data still gets a working theme, just not a sticky one.
    return fallback;
  }
}

/** Apply the resolved theme class to `<html>`, mirroring what the pre-hydration script does. */
function applyTheme(theme: Theme) {
  const root = window.document.documentElement;
  const resolved =
    theme === 'system'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : theme;

  root.classList.remove('light', 'dark');
  root.classList.add(resolved);
}

/**
 * Provides the theme preference and the setter that persists it.
 *
 * State is seeded from `localStorage` in the initialiser rather than in an effect: reading it
 * afterwards produced a second flash, where the system theme was applied first and the stored
 * preference re-applied a tick later. The provider renders no theme-dependent markup itself, so
 * seeding from storage on the client cannot cause a hydration mismatch.
 */
export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = THEME_STORAGE_KEY,
  ...props
}: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme(storageKey, defaultTheme));

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    // Following the OS only matters while the user has chosen to follow it.
    if (theme !== 'system') {
      return;
    }
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => applyTheme('system');
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme: (newTheme: Theme) => {
        try {
          window.localStorage.setItem(storageKey, newTheme);
        } catch {
          // Preference is not persisted, but the theme still applies for this session.
        }
        setTheme(newTheme);
      },
    }),
    [theme, storageKey]
  );

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext);
  if (context === undefined)
    throw new Error('useTheme must be used within a ThemeProvider');
  return context;
};
