import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';

import '@/styles/globals.css';

// Inter carries dense prose and long question prompts; JetBrains Mono carries scores, category
// labels and progress counters, where tabular numerals and a technical register matter.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
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
  // The product is dark by default; declaring it prevents a white flash before CSS loads.
  colorScheme: 'dark',
  themeColor: '#0a0e15',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
