import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, Activity, Zap, CheckCircle2 } from 'lucide-react';
import { GradedAnswerDemo } from '@/features/marketing/components/GradedAnswerDemo';
import { MarketingNavbar } from '@/features/marketing/components/MarketingNavbar';
import { MarketingFooter } from '@/features/marketing/components/MarketingFooter';
import { HeroVisual } from '@/features/marketing/components/HeroVisual';
import { GridBackground } from '@/components/layout/GridBackground';
import { recordEvent } from '@/lib/api/analytics';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'LRN — Know whether you are ready before the interview does',
  description:
    'A free 24-question diagnostic, graded against a real rubric, that tells you which technical categories you are actually weak in before an interviewer finds out for you.',
};

export default async function HomePage() {
  await recordEvent('landing_view');

  return (
    <div className="relative min-h-dvh flex flex-col selection:bg-accent-muted selection:text-text-primary">
      <GridBackground />
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-md focus:border focus:border-border-strong focus:bg-surface-elevated focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Skip to content
      </a>
      <MarketingNavbar />

      <main id="main-content" className="flex-1 flex flex-col items-center pt-16">
        {/* Hero Section */}
        <section className="relative w-full px-6 pt-24 pb-20 md:pt-36 md:pb-32 flex flex-col items-center text-center">
          <HeroVisual />
          
          <div className="relative z-10 max-w-4xl space-y-8 animate-in fade-in slide-in-from-bottom-6 duration-1000 ease-out">
            <h1 className="text-4xl leading-[1.15] font-semibold tracking-tight text-text-primary sm:text-5xl md:text-6xl lg:text-[4.5rem]">
              Deliberate practice for <br className="hidden sm:block"/> technical interviews.
            </h1>
            <p className="mx-auto max-w-2xl text-lg leading-relaxed text-text-secondary md:text-xl font-medium">
              A finance-focused practice and learning platform that helps you improve through deliberate practice, evaluation, and precise feedback.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-6">
              <Link
                href="/signup"
                className="group flex h-12 w-full sm:w-auto items-center justify-center gap-2 rounded-full bg-text-primary px-8 text-base font-medium text-canvas transition-all hover:bg-text-secondary hover:scale-[1.02] shadow-xl shadow-text-primary/10"
              >
                Start free diagnostic
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
              <Link
                href="#how-it-works"
                className="flex h-12 w-full sm:w-auto items-center justify-center rounded-full border border-border-strong bg-surface-1/50 backdrop-blur-sm px-8 text-base font-medium text-text-primary transition-colors hover:bg-surface-2"
              >
                See how it works
              </Link>
            </div>
          </div>
        </section>

        {/* Practice Loop Explanation */}
        <section id="how-it-works" className="relative z-10 w-full max-w-6xl px-6 py-20">
          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                icon: Activity,
                title: 'Adaptive Practice',
                desc: 'Answer questions drawn from your weakest categories and spaced-repetition misses.',
              },
              {
                icon: Zap,
                title: 'AI Evaluation',
                desc: 'Get immediate feedback on your answers graded against rigorous rubrics.',
              },
              {
                icon: CheckCircle2,
                title: 'Targeted Growth',
                desc: 'Review exactly which concepts you missed and study the reference answer.',
              }
            ].map((feature, i) => (
              <div 
                key={i} 
                className="flex flex-col items-start p-8 rounded-2xl border border-border-subtle bg-surface-1/40 backdrop-blur-md transition-all duration-300 hover:bg-surface-2/60 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-muted/50 text-accent mb-6 border border-accent/10">
                  <feature.icon className="h-6 w-6" />
                </div>
                <h3 className="text-xl font-semibold text-text-primary mb-3 tracking-tight">{feature.title}</h3>
                <p className="text-sm leading-relaxed text-text-secondary">{feature.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Visual Preview */}
        <section className="relative z-10 w-full max-w-5xl px-6 pb-24 lg:pb-32">
          <div className="rounded-2xl border border-border-strong bg-surface-1/50 backdrop-blur-sm p-3 shadow-2xl relative group overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-tr from-accent/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
            <div className="rounded-xl border border-border-subtle bg-canvas overflow-hidden relative">
              <div className="border-b border-border-subtle bg-surface-2/80 backdrop-blur-md px-4 py-3 flex items-center gap-2">
                <div className="flex gap-1.5">
                  <div className="h-3 w-3 rounded-full bg-border-strong" />
                  <div className="h-3 w-3 rounded-full bg-border-strong" />
                  <div className="h-3 w-3 rounded-full bg-border-strong" />
                </div>
                <span className="text-xs font-mono text-text-muted ml-3">lrn.dev / diagnostic</span>
              </div>
              <div className="p-0 sm:p-10 bg-canvas/90">
                <GradedAnswerDemo />
              </div>
            </div>
          </div>
        </section>
      </main>

      <MarketingFooter />
    </div>
  );
}
