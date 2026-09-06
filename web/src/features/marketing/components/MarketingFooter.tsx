import Link from 'next/link';

/** The public site footer. Shared by every page that renders without the signed-in app shell. */
export function MarketingFooter() {
  return (
    <footer className="relative z-10 border-t border-border-subtle bg-surface-1/50 py-12 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-6 px-6 text-sm md:flex-row">
        <span className="label-micro text-text-muted">LRN © 2026</span>
        <nav aria-label="Footer" className="flex gap-8 text-text-muted">
          <Link href="/pricing" className="font-medium transition-colors hover:text-text-primary">
            Pricing
          </Link>
          <Link href="/glossary" className="font-medium transition-colors hover:text-text-primary">
            Glossary
          </Link>
          <Link href="/signin" className="font-medium transition-colors hover:text-text-primary">
            Sign in
          </Link>
        </nav>
      </div>
    </footer>
  );
}
