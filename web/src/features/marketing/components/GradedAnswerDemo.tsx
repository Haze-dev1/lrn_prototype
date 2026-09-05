/**
 * A real graded answer, marked up.
 *
 * This is the landing page's argument, and it is shown rather than described. Every other claim a
 * product like this makes — "AI-powered feedback", "personalised practice" — is a sentence anyone
 * can write. A marked script is the artifact only this product actually produces.
 *
 * The mark-up encodes the thing that is genuinely hard and genuinely valuable: the grader reports
 * what the answer established *and what it left out*. Concepts the student earned are underlined
 * in their own words; the two they missed are hung off the answer as a marker's note. A reader
 * understands the product from this block without reading a word of marketing copy.
 *
 * The content is fixed and hand-authored. It is a worked example, not live data, and the answer
 * is a plausible two-thirds answer rather than a strawman — a student who reads it should
 * recognise their own reasoning, which is what makes the missing pieces land.
 */
export function GradedAnswerDemo() {
  return (
    <figure className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6 md:p-8">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="label-micro">Enterprise &amp; equity value · Question 4 of 24</span>
        <span className="label-micro">
          Difficulty{' '}
          <span aria-hidden="true" className="text-text-secondary">
            ▮▮▯▯▯
          </span>
          <span className="sr-only">2 of 5</span>
        </span>
      </figcaption>

      <p className="mt-4 text-lg leading-snug font-medium text-text-primary md:text-xl">
        Walk me through how you get from enterprise value to equity value.
      </p>

      <div className="mt-6 border-t border-border-subtle pt-5">
        <p className="label-micro">The answer</p>
        <p className="mt-3 leading-loose text-text-secondary">
          You start with enterprise value and{' '}
          <span className="concept-hit">subtract net debt</span>, which is total debt{' '}
          <span className="concept-hit">minus cash</span>. That gets you to equity value.
        </p>

        {/* The absences, as a margin note rather than inside the sentence. Dropping them into the
            prose read as broken text — the reader repairs the grammar before they notice the
            point. Hung off the answer instead, they read as what they are: the grader marking
            what should have been there. */}
        <p className="mt-3 flex flex-wrap items-center gap-2 border-l-2 border-band-needs-work/40 pl-3 text-sm text-text-muted">
          <span className="label-micro text-band-needs-work">Not found</span>
          <span className="concept-missing">minority interest</span>
          <span className="concept-missing">preferred stock</span>
        </p>

        <p className="mt-4 text-xs text-text-muted">
          Underlined in the answer: established. Below it: looked for, and not there.
        </p>
      </div>

      {/* The reveal. In the product this appears when grading resolves; here it arrives a beat
          after the answer, which is the same order a student experiences. */}
      <div
        className="reveal mt-6 border-t border-border-subtle pt-5"
        style={{ animationDelay: '450ms' }}
      >
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <span className="tabular font-mono text-4xl leading-none font-semibold text-band-developing">
            68
          </span>
          <span className="label-micro text-band-developing">Developing</span>
        </div>

        <p className="mt-4 leading-relaxed text-text-secondary">
          Two of the four bridge items. Minority interest and preferred stock are claims on the
          business that a buyer takes on, so they belong in the bridge — add them and this is a
          complete answer.
        </p>
      </div>
    </figure>
  );
}
