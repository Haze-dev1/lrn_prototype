'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { glossaryTerms, type GlossaryTerm } from '../data/terms';

/** Every surface form that should resolve to a term: the heading itself plus its aliases. */
interface Surface {
  form: string;
  term: GlossaryTerm;
}

const SURFACES: Surface[] = glossaryTerms
  .flatMap((term) => [term.term, ...(term.aliases ?? [])].map((form) => ({ form, term })))
  // Longest first, so "three financial statements" wins over "financial statements" and
  // "over-levered" over "levered".
  .sort((a, b) => b.form.length - a.form.length);

const SURFACE_BY_FORM = new Map(SURFACES.map((s) => [s.form.toLowerCase(), s.term]));

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Space between the term and its popover, matching the `mb-2` / `mt-2` below. */
const GAP = 8;

const TERM_PATTERN = new RegExp(
  `\\b(${SURFACES.map((s) => escapeRegExp(s.form)).join('|')})\\b`,
  'gi'
);

/**
 * Render text with known glossary terms turned into definition popovers.
 *
 * Only the first occurrence of each term is linked: a prompt that says "depreciation" four times
 * should offer the definition once, not turn the question into a wall of links.
 */
export function InlineGlossaryText({ text }: { text: string }) {
  const parts = useMemo(() => {
    const pattern = new RegExp(TERM_PATTERN.source, TERM_PATTERN.flags);
    const seen = new Set<string>();
    const output: Array<string | { key: string; term: GlossaryTerm; matched: string }> = [];

    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = pattern.exec(text)) !== null) {
      const matched = match[0];
      const term = SURFACE_BY_FORM.get(matched.toLowerCase());

      if (term && !seen.has(term.id)) {
        seen.add(term.id);
        if (match.index > lastIndex) {
          output.push(text.slice(lastIndex, match.index));
        }
        output.push({ key: `${term.id}-${match.index}`, term, matched });
        lastIndex = pattern.lastIndex;
      }
    }

    if (lastIndex < text.length) {
      output.push(text.slice(lastIndex));
    }

    return output;
  }, [text]);

  return (
    <>
      {parts.map((part, index) =>
        typeof part === 'string' ? (
          <span key={`t-${index}`}>{part}</span>
        ) : (
          <GlossaryPopover key={part.key} term={part.term} label={part.matched} />
        )
      )}
    </>
  );
}

function GlossaryPopover({ term, label }: { term: GlossaryTerm; label: string }) {
  const [isOpen, setIsOpen] = useState(false);
  // Below the term by default, flipping above only when the viewport leaves no room there.
  // Everything a runner puts above the prompt — the progress rail, the "Question 4 of 24"
  // line — is exactly what a popover placed above would cover.
  const [placement, setPlacement] = useState<'top' | 'bottom'>('bottom');
  const triggerRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const descriptionId = useId();

  const close = useCallback(() => setIsOpen(false), []);

  useLayoutEffect(() => {
    if (!isOpen || !triggerRef.current || !tooltipRef.current) {
      return;
    }
    // Measured, not assumed: the height depends on how long the definition is. This runs
    // before paint, so a correction is never visible.
    const trigger = triggerRef.current.getBoundingClientRect();
    const needed = tooltipRef.current.getBoundingClientRect().height + GAP;
    const fitsBelow = trigger.bottom + needed <= window.innerHeight;
    const fitsAbove = trigger.top - needed >= 0;
    setPlacement(!fitsBelow && fitsAbove ? 'top' : 'bottom');
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, close]);

  return (
    <span
      className="relative inline-block"
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={close}
      onFocus={() => setIsOpen(true)}
      onBlur={close}
    >
      <button
        ref={triggerRef}
        type="button"
        // A real toggle, so the definition is reachable by tap as well as by hover, and
        // `aria-expanded` describes something that can actually be operated.
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-describedby={descriptionId}
        className="font-medium text-accent underline decoration-dashed decoration-accent/30 underline-offset-4 transition-colors hover:decoration-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
      >
        {label}
      </button>

      {/* One element serves both audiences: it is the visible popover when open and an
          off-screen description the whole time, so `aria-describedby` always resolves and a
          screen reader announces the definition when the term takes focus. */}
      <span
        ref={tooltipRef}
        id={descriptionId}
        role="tooltip"
        className={
          isOpen
            ? `absolute left-1/2 z-50 block w-64 -translate-x-1/2 rounded-md border border-border-strong bg-surface-elevated p-3 shadow-popover animate-in fade-in zoom-in-95 duration-200 ${
                placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'
              }`
            : 'sr-only'
        }
      >
        <span className="mb-1 block text-sm font-semibold text-text-primary">{term.term}</span>
        <span className="block text-xs leading-relaxed text-text-secondary">
          {term.definition}
        </span>

        {isOpen ? (
          <span
            aria-hidden="true"
            className={`absolute left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 bg-surface-elevated ${
              placement === 'top'
                ? '-mt-px top-full border-b border-r border-border-strong'
                : '-mb-px bottom-full border-l border-t border-border-strong'
            }`}
          />
        ) : null}
      </span>
    </span>
  );
}
