'use client';

import Link from 'next/link';
import { useState, useEffect } from 'react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { cn } from '@/utils/cn';
import { Menu, X } from 'lucide-react';

export function MarketingNavbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <header 
      className={cn(
        "fixed top-0 inset-x-0 z-50 transition-all duration-300 border-b",
        scrolled 
          ? "bg-canvas/80 backdrop-blur-xl border-border-subtle shadow-sm" 
          : "bg-transparent border-transparent"
      )}
    >
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6">
        <Link href="/" className="label-micro text-text-primary hover:text-accent transition-colors">
          LRN
        </Link>
        
        {/* Desktop Nav */}
        <nav aria-label="Marketing" className="hidden md:flex items-center gap-6">
          <Link href="/pricing" className="text-sm font-medium text-text-secondary transition-colors hover:text-text-primary">
            Pricing
          </Link>
          <Link href="/glossary" className="text-sm font-medium text-text-secondary transition-colors hover:text-text-primary">
            Glossary
          </Link>
          
          <div className="w-px h-4 bg-border-strong mx-2" />
          
          <ThemeToggle />
          
          <Link href="/signin" className="text-sm font-medium text-text-secondary transition-colors hover:text-text-primary ml-2">
            Sign in
          </Link>
          <Link
            href="/signup"
            className="rounded-full bg-text-primary px-4 py-1.5 text-sm font-medium text-canvas transition-all hover:bg-text-secondary hover:scale-105 shadow-md active:scale-95"
          >
            Sign up
          </Link>
        </nav>

        {/* Mobile Toggle */}
        <div className="flex md:hidden items-center gap-4">
          <ThemeToggle />
          <button 
            className="p-1 text-text-secondary hover:text-text-primary transition-colors focus:outline-none"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      <div 
        className={cn(
          "md:hidden absolute inset-x-0 top-16 bg-surface-1 border-b border-border-subtle shadow-lg transition-all duration-300 ease-in-out overflow-hidden origin-top",
          mobileMenuOpen ? "opacity-100 scale-y-100 h-auto py-4" : "opacity-0 scale-y-0 h-0 py-0 pointer-events-none"
        )}
      >
        <nav className="flex flex-col px-6 gap-4">
          <Link 
            href="/pricing" 
            className="text-base font-medium text-text-secondary hover:text-text-primary"
            onClick={() => setMobileMenuOpen(false)}
          >
            Pricing
          </Link>
          <Link 
            href="/glossary" 
            className="text-base font-medium text-text-secondary hover:text-text-primary"
            onClick={() => setMobileMenuOpen(false)}
          >
            Glossary
          </Link>
          <div className="h-px w-full bg-border-subtle my-2" />
          <Link 
            href="/signin" 
            className="text-base font-medium text-text-secondary hover:text-text-primary"
            onClick={() => setMobileMenuOpen(false)}
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="w-full text-center rounded-md bg-text-primary px-4 py-3 text-base font-medium text-canvas transition-colors hover:bg-text-secondary"
            onClick={() => setMobileMenuOpen(false)}
          >
            Start Free Diagnostic
          </Link>
        </nav>
      </div>
    </header>
  );
}
