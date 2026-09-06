'use client';

import { useResolvedTheme } from '@/hooks/useResolvedTheme';

export function GridBackground() {
  const resolved = useResolvedTheme();

  // Null before hydration, and it stays a neutral placeholder rather than guessing a palette
  // and repainting a full-bleed background a tick later.
  if (!resolved) {
    return <div className="absolute inset-0 -z-20 opacity-0" />;
  }

  const isDark = resolved === 'dark';

  return (
    <div className="pointer-events-none absolute inset-0 -z-20 overflow-hidden">
      {/* Background radial gradient to give depth behind the grid */}
      <div 
        className="absolute inset-0"
        style={{
          background: isDark 
            ? 'radial-gradient(circle at 50% 0%, var(--color-accent-muted) 0%, transparent 70%)'
            : 'radial-gradient(circle at 50% 0%, var(--color-surface-2) 0%, transparent 70%)',
          opacity: 0.4
        }}
      />
      
      {/* The actual grid */}
      <div 
        className="absolute inset-0"
        style={{
          backgroundImage: isDark
            ? `
              linear-gradient(to right, rgba(255, 255, 255, 0.03) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(255, 255, 255, 0.03) 1px, transparent 1px)
            `
            : `
              linear-gradient(to right, rgba(0, 0, 0, 0.03) 1px, transparent 1px),
              linear-gradient(to bottom, rgba(0, 0, 0, 0.03) 1px, transparent 1px)
            `,
          backgroundSize: '40px 40px',
          maskImage: 'radial-gradient(ellipse at 50% 20%, black 20%, transparent 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse at 50% 20%, black 20%, transparent 80%)',
        }}
      />
    </div>
  );
}
