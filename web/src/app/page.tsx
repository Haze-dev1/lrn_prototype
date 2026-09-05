import type { Metadata } from 'next';
import Link from 'next/link';

import { GradedAnswerDemo } from '@/features/marketing/components/GradedAnswerDemo';
import { MasteryDemo } from '@/features/marketing/components/MasteryDemo';
import { ProductLoop } from '@/features/marketing/components/ProductLoop';
import { recordEvent } from '@/lib/api/analytics';
import { fetchPlans } from '@/lib/api/billing';

// Rendered per request: the pricing strip reads the live plan catalogue, and a plan that is not
// on sale must not be advertised as though it were.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'LRN — Know whether you are ready before the interview does',
  description:
    'A free 24-question diagnostic, graded against a real rubric, that tells you which technical '
    + 'categories you are actually weak in before an interviewer finds out for you.',
};

/**
 * The marketing landing page.
 *
 * Its whole job is to get a student to start the diagnostic, and the argument it makes is a
 * demonstration rather than a claim: the first thing below the headline is a marked answer with a
 * score, the concepts it established and the two it missed. Anyone can write "AI-powered
 * feedback"; almost nobody can show the artifact.
 *
 * Ships no client JavaScript. The one moment of motion — the grade arriving a beat after the
 * answer — is a CSS keyframe, so the page is a Server Component end to end and the reader pays
 * nothing for the effect.
 */
export default async function HomePage() {
  // The head of the funnel. Recorded from the server render, so no analytics script reaches the
  // browser and nothing here is blocked by an ad blocker. It never throws.
  await recordEvent('landing_view');

  const { plans, billing_enabled } = await fetchPlans().catch(() => ({
    plans: [],
    billing_enabled: false,
  }));
  const paidPlans = plans.filter((plan) => plan.plan !== 'free');

  return (
    <div className="min-h-dvh">
      <header className="border-b border-border-subtle">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-6 py-4">
          <span className="label-micro text-text-secondary">LRN</span>
          <nav aria-label="Marketing" className="flex items-center gap-1">
            <Link
              href="/pricing"
              className="rounded-md px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              Pricing
            </Link>
            <Link
              href="/signin"
              className="rounded-md px-3 py-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* Hero. The headline states the promise; the block underneath is the evidence for it. */}
        <section className="mx-auto w-full max-w-5xl px-6 pt-16 pb-20 md:pt-24">
          <div className="max-w-2xl">
            <h1 className="text-4xl leading-[1.05] font-semibold tracking-tight text-balance text-text-primary sm:text-5xl md:text-6xl">
              Know whether you&rsquo;re ready before the interview does.
            </h1>
            <p className="mt-6 max-w-xl text-base leading-relaxed text-text-secondary md:text-lg">
              Twenty-four questions, graded against a real rubric, that tell you which technical
              categories you are actually weak in — while there is still time to fix them.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/signup"
                className="inline-flex h-12 items-center justify-center rounded-md bg-text-primary px-6 text-base font-medium text-text-inverse transition-colors hover:bg-white"
              >
                Take the free diagnostic
              </Link>
              <Link
                href="#grading"
                className="inline-flex h-12 items-center justify-center rounded-md border border-border-subtle px-6 text-base text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
              >
                See how grading works
              </Link>
            </div>

            <p className="mt-4 text-sm text-text-muted">
              Free, no card. The diagnostic is graded in full.
            </p>
          </div>

          <div id="grading" className="mt-14 scroll-mt-8">
            <GradedAnswerDemo />
          </div>
        </section>

        {/* The problem. Stated once, in the student's own situation, and not repeated. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto w-full max-w-5xl px-6 py-16 md:py-20">
            <p className="label-micro">The problem</p>
            <p className="mt-5 max-w-3xl text-2xl leading-snug font-medium text-balance text-text-primary md:text-3xl">
              You have read the guides and you can recite the three statements. Then someone asks
              you to walk them through a DCF, and you find out which parts you only half knew — in
              real time, in front of the person deciding.
            </p>
            <p className="mt-6 max-w-2xl leading-relaxed text-text-secondary">
              Preparation fails quietly. Reading feels like progress, recognising an answer feels
              like knowing it, and nothing in a guide tells you which of the eight technical areas
              will be the one that catches you. LRN&rsquo;s job is to find that out first.
            </p>
          </div>
        </section>

        {/* The loop. A real sequence, so it is numbered, and it closes. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto w-full max-w-5xl px-6 py-16 md:py-20">
            <div className="max-w-2xl">
              <p className="label-micro">The loop</p>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-text-primary md:text-3xl">
                Five steps, and then the first one again.
              </h2>
            </div>
            <div className="mt-8">
              <ProductLoop />
            </div>
            <p className="mt-5 max-w-2xl text-sm leading-relaxed text-text-muted">
              It is a cycle, not a course. You are finished when the number is where you need it,
              which is a thing you can check rather than a feeling you have to trust.
            </p>
          </div>
        </section>

        {/* Mastery. The measurement the diagnostic produces. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto grid w-full max-w-5xl gap-10 px-6 py-16 md:py-20 lg:grid-cols-[1fr_1.1fr] lg:items-center">
            <div className="max-w-lg">
              <p className="label-micro">What you get back</p>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-text-primary md:text-3xl">
                Eight categories, one number each, and the evidence behind every one.
              </h2>
              <p className="mt-5 leading-relaxed text-text-secondary">
                Mastery is weighted towards your recent answers, so it reflects where you are now
                rather than where you started. A category you have not been asked about stays
                unmeasured — the product will not invent a score it has no evidence for.
              </p>
            </div>
            <MasteryDemo />
          </div>
        </section>

        {/* Adaptive practice, and the claim that it is explainable. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto w-full max-w-5xl px-6 py-16 md:py-20">
            <div className="max-w-2xl">
              <p className="label-micro">Practice</p>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-text-primary md:text-3xl">
                Every set tells you why it chose what it chose.
              </h2>
              <p className="mt-5 leading-relaxed text-text-secondary">
                Questions are drawn from your weakest categories, from the misses whose spacing
                interval has elapsed, and from material you have not seen. The interface says which
                of those drove the set — and it can say it because that is genuinely how the set
                was built.
              </p>
            </div>

            <figure className="mt-8 max-w-2xl rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6">
              <blockquote className="text-lg leading-relaxed text-text-primary">
                &ldquo;Valuation is currently your weakest category, and 2 previous misses are due
                for review.&rdquo;
              </blockquote>
              <figcaption className="mt-3 text-xs text-text-muted">
                Written when the set was composed, and stored with it — not reconstructed
                afterwards from a state that has since moved.
              </figcaption>
            </figure>
          </div>
        </section>

        {/* Pricing. Compact, honest about the free tier, and it defers to the pricing page. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto w-full max-w-5xl px-6 py-16 md:py-20">
            <div className="max-w-2xl">
              <p className="label-micro">Pricing</p>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-text-primary md:text-3xl">
                The diagnostic is free. Closing the gaps is what you pay for.
              </h2>
            </div>

            <div className="mt-8 grid gap-px overflow-hidden rounded-[--radius-card] border border-border-subtle bg-border-subtle sm:grid-cols-3">
              <div className="bg-canvas p-5">
                <h3 className="text-base font-medium text-text-primary">Free</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  The full 24-question diagnostic, graded. Your category mastery, your weakest
                  area, and a few practice sets.
                </p>
              </div>
              {paidPlans.map((plan) => (
                <div key={plan.plan} className="bg-canvas p-5">
                  <h3 className="text-base font-medium text-text-primary">{plan.name}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">{plan.tagline}</p>
                  <p className="mt-3 text-sm text-text-secondary">{plan.features[0]}</p>
                </div>
              ))}
            </div>

            <p className="mt-5 text-sm text-text-muted">
              <Link href="/pricing" className="text-accent underline-offset-4 hover:underline">
                Compare the plans
              </Link>
              {billing_enabled ? null : ' — payments are not available in this deployment.'}
            </p>
          </div>
        </section>

        {/* The close. One action, and it is the same one the hero offered. */}
        <section className="border-t border-border-subtle">
          <div className="mx-auto w-full max-w-5xl px-6 py-20 text-center md:py-24">
            <h2 className="mx-auto max-w-2xl text-3xl font-semibold tracking-tight text-balance text-text-primary md:text-4xl">
              Find out where you stand in about forty minutes.
            </h2>
            <p className="mx-auto mt-5 max-w-xl leading-relaxed text-text-secondary">
              Twenty-four questions across all eight categories. You will leave knowing your
              weakest area, the concepts you missed, and what to do next.
            </p>
            <Link
              href="/signup"
              className="mt-8 inline-flex h-12 items-center justify-center rounded-md bg-text-primary px-6 text-base font-medium text-text-inverse transition-colors hover:bg-white"
            >
              Take the free diagnostic
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border-subtle">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-8">
          <span className="label-micro text-text-muted">LRN</span>
          <nav aria-label="Footer" className="flex flex-wrap items-center gap-5 text-sm">
            <Link href="/pricing" className="text-text-muted transition-colors hover:text-text-secondary">
              Pricing
            </Link>
            <Link href="/signin" className="text-text-muted transition-colors hover:text-text-secondary">
              Sign in
            </Link>
            <Link href="/signup" className="text-text-muted transition-colors hover:text-text-secondary">
              Create an account
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
