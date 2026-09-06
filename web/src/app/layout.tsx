import type { Metadata, Viewport } from 'next';
import { Plus_Jakarta_Sans, JetBrains_Mono } from 'next/font/google';

import '@/styles/globals.css';
import { ThemeProvider } from '@/components/layout/ThemeProvider';
import { THEME_INIT_SCRIPT } from '@/components/layout/theme-script';

const primaryFont = Plus_Jakarta_Sans({ subsets: ['latin'], variable: '--font-primary', display: 'swap' });
// Bound to `--font-mono-raw`, not `--font-mono`: the theme token in globals.css reads
// `var(--font-mono-raw), ui-monospace, …`, and naming both the same made that declaration
// self-referential and silently dropped the fallback chain.
const monoFont = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono-raw',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {
    default: 'LRN — Technical interview readiness',
    template: '%s · LRN',
  },
  description:
    'LRN grades your actual answers to investment banking and private equity technical questions, shows exactly which concepts you missed, and adapts your practice to close the gap.',
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fcfcfc' },
    { media: '(prefers-color-scheme: dark)', color: '#101216' },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${primaryFont.variable} ${monoFont.variable}`} suppressHydrationWarning>
      <head>
        {/* Blocking, and before anything paints: an effect-applied theme flashes the classless
            dark default on every full load for anyone whose theme is light. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-dvh antialiased text-text-primary bg-canvas">
        <ThemeProvider>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
