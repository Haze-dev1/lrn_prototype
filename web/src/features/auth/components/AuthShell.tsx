/** Shared layout for the sign-in and sign-up screens. */

import Link from 'next/link';
import type { ReactNode } from 'react';

export interface AuthShellProps {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}

export function AuthShell({ title, subtitle, children, footer }: AuthShellProps) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-8 px-6 py-16">
      <div className="space-y-3">
        <Link href="/" className="label-micro transition-colors hover:text-text-secondary">
          LRN
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">{title}</h1>
        <p className="text-sm leading-relaxed text-text-secondary">{subtitle}</p>
      </div>

      <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6">
        {children}
      </div>

      <p className="text-center text-sm text-text-secondary">{footer}</p>
    </main>
  );
}
