'use client';

import { useTheme } from './ThemeProvider';
import { Moon, Sun } from 'lucide-react';
import { useResolvedTheme } from '@/hooks/useResolvedTheme';

export function ThemeToggle() {
  const { setTheme } = useTheme();
  // Null until hydration: the server cannot know which icon is correct, and rendering one
  // anyway is a hydration mismatch.
  const resolved = useResolvedTheme();

  if (!resolved) {
    return <div className="w-8 h-8 rounded-md bg-surface-2 animate-pulse" />;
  }

  return (
    <button
      onClick={() => setTheme(resolved === 'dark' ? 'light' : 'dark')}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border-subtle bg-surface-1 text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      aria-label={`Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme`}
    >
      {resolved === 'dark' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
    </button>
  );
}
