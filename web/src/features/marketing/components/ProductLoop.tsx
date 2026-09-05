const STEPS = [
  {
    verb: 'Answer',
    line: 'You write it out, the way you would say it across the table. No multiple choice.',
  },
  {
    verb: 'Evaluate',
    line: 'Graded against the same rubric a good interviewer carries in their head.',
  },
  {
    verb: 'Understand',
    line: 'What you established, what you left out, and why the gap matters.',
  },
  {
    verb: 'Practise',
    line: 'A set built from your weakest categories and the misses that are due to come back.',
  },
  {
    verb: 'Improve',
    line: 'The number moves — or it does not, which is also worth knowing.',
  },
];

/**
 * The product loop.
 *
 * Rendered as a numbered sequence because it genuinely is one: the order carries information a
 * reader needs, and the fifth step returns to the first. That return is the whole thesis — the
 * product is not a course you finish, it is a cycle you run until the number is where you need
 * it — so the sequence closes rather than trailing off, and the closing line says so.
 */
export function ProductLoop() {
  return (
    <ol className="grid gap-px overflow-hidden rounded-[--radius-card] border border-border-subtle bg-border-subtle sm:grid-cols-2 lg:grid-cols-5">
      {STEPS.map((step, index) => {
        const last = index === STEPS.length - 1;
        return (
          <li key={step.verb} className="flex flex-col bg-canvas p-5">
            <span className="label-micro tabular">
              {String(index + 1).padStart(2, '0')}
              {/* The last step returns to the first, so the numbering says so. Without this the
                  heading claims a loop and the layout draws a list that stops. */}
              {last ? <span className="text-accent"> &rarr; 01</span> : null}
            </span>
            <h3 className="mt-3 text-base font-medium text-text-primary">{step.verb}</h3>
            <p className="mt-2 text-sm leading-relaxed text-text-secondary">{step.line}</p>
          </li>
        );
      })}
    </ol>
  );
}
