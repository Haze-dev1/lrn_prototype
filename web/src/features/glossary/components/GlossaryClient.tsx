'use client';

import { useState, useMemo } from 'react';
import { GLOSSARY_CATEGORIES, glossaryTerms, type GlossaryCategory } from '../data/terms';
import { Search, Book, ArrowRight } from 'lucide-react';

export function GlossaryClient() {
  const [search, setSearch] = useState('');
  
  // Listed in the product's own taxonomy order rather than alphabetically, and only the
  // categories that actually have terms, so the sidebar never offers an empty filter.
  const categories = useMemo(() => {
    const populated = new Set(glossaryTerms.map((t) => t.category));
    return GLOSSARY_CATEGORIES.filter((category) => populated.has(category));
  }, []);

  const [selectedCategory, setSelectedCategory] = useState<GlossaryCategory | null>(null);

  const filteredTerms = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return glossaryTerms
      .filter((term) => {
        // Aliases are searched too: someone looking for "discounted cash flow" should find DCF.
        const matchesSearch =
          !needle ||
          term.term.toLowerCase().includes(needle) ||
          term.definition.toLowerCase().includes(needle) ||
          (term.aliases ?? []).some((alias) => alias.toLowerCase().includes(needle));
        const matchesCategory = selectedCategory ? term.category === selectedCategory : true;
        return matchesSearch && matchesCategory;
      })
      .sort((a, b) => a.term.localeCompare(b.term));
  }, [search, selectedCategory]);

  return (
    <div className="space-y-10 animate-in fade-in duration-700">
      <header className="border-b border-border-subtle pb-8">
        <div className="flex items-center gap-3 mb-4">
          <Book className="w-8 h-8 text-accent" />
          <h1 className="text-3xl font-semibold tracking-tight text-text-primary">Financial Glossary</h1>
        </div>
        <p className="text-base text-text-secondary max-w-2xl">
          A comprehensive reference of financial concepts, formulas, and terminology to support your technical interview preparation.
        </p>
      </header>

      <div className="flex flex-col md:flex-row gap-8">
        {/* Sidebar Controls */}
        <aside className="w-full md:w-64 shrink-0 space-y-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
            <input
              type="text"
              placeholder="Search terms..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-md border border-border-strong bg-surface-1 py-2 pl-9 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent transition-colors"
            />
          </div>

          <div>
            <h3 className="label-micro mb-3">Categories</h3>
            <ul className="space-y-1">
              <li>
                <button
                  onClick={() => setSelectedCategory(null)}
                  className={`w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors ${
                    selectedCategory === null 
                      ? 'bg-accent/10 text-accent font-medium' 
                      : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary'
                  }`}
                >
                  All Terms
                </button>
              </li>
              {categories.map(category => (
                <li key={category}>
                  <button
                    onClick={() => setSelectedCategory(category)}
                    className={`w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors ${
                      selectedCategory === category 
                        ? 'bg-accent/10 text-accent font-medium' 
                        : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary'
                    }`}
                  >
                    {category}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        {/* Content */}
        <div className="flex-1 space-y-6">
          {filteredTerms.length === 0 ? (
            <div className="rounded-[--radius-lg] border border-border-subtle bg-surface-1 p-12 text-center">
              <p className="text-text-secondary">No terms found matching your search.</p>
              <button 
                onClick={() => { setSearch(''); setSelectedCategory(null); }}
                className="mt-4 text-sm text-accent hover:underline"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-8 divide-y divide-border-subtle border-t border-border-subtle pt-6">
              {filteredTerms.map(term => (
                <article 
                  key={term.id} 
                  className="pt-8 first:pt-0"
                >
                  <div className="flex flex-col gap-2 mb-4">
                    <h2 className="text-2xl font-medium text-text-primary">
                      {term.term}
                    </h2>
                    <span className="text-xs font-mono tracking-widest uppercase text-text-muted">
                      {term.category}
                    </span>
                  </div>
                  <p className="text-base text-text-secondary leading-relaxed mb-6 max-w-3xl">
                    {term.definition}
                  </p>
                  {term.explanation && (
                    <div className="text-base text-text-primary pl-4 border-l-2 border-accent mb-6 max-w-3xl italic">
                      {term.explanation}
                    </div>
                  )}
                  {term.related && term.related.length > 0 && (
                    <div className="flex flex-wrap items-baseline gap-3">
                      <span className="label-micro text-text-muted">SEE ALSO:</span>
                      {term.related.map(rId => {
                        const rTerm = glossaryTerms.find(t => t.id === rId);
                        if (!rTerm) return null;
                        return (
                          <button 
                            key={rId}
                            onClick={() => { setSearch(rTerm.term); setSelectedCategory(null); }}
                            className="text-sm font-medium text-text-primary hover:text-accent transition-colors underline decoration-border-strong underline-offset-4"
                          >
                            {rTerm.term}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
