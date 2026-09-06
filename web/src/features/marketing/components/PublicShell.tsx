import type { ReactNode } from 'react';

import { MarketingNavbar } from './MarketingNavbar';
import { MarketingFooter } from './MarketingFooter';

/**
 * Chrome for a public page viewed without a session.
 *
 * Pages reachable both signed out and signed in render this or `AppShell` depending on who is
 * asking — a visitor who arrives from the public navbar must not land somewhere with no way back.
 * The top padding clears the navbar, which is fixed.
 */
export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas text-text-primary">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:border focus:border-border-strong focus:bg-surface-elevated focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Skip to content
      </a>

      <MarketingNavbar />

      <div id="main-content" className="flex flex-1 flex-col pt-16">
        {children}
      </div>

      <MarketingFooter />
    </div>
  );
}
