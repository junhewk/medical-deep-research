"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Plus,
  Settings,
  Sun,
  Moon,
  Menu,
  X,
  FileText,
  Dna,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/research", label: "Research", icon: FileText },
  { href: "/research/new", label: "New Query", icon: Plus, highlight: true },
  { href: "/settings/api-keys", label: "Settings", icon: Settings },
];

export function Navigation() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    setMounted(true);

    const handleScroll = () => {
      setScrolled(window.scrollY > 10);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const isActive = (href: string) => {
    if (href === "/research") {
      return pathname === "/research" || pathname === "/";
    }
    return pathname.startsWith(href);
  };

  return (
    <header
      className={cn(
        "sticky top-0 z-50 transition-all duration-300",
        scrolled
          ? "bg-background/85 backdrop-blur-xl border-b border-border/50 shadow-sm"
          : "bg-transparent border-b border-transparent"
      )}
    >
      <div className="container">
        <nav className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/research" className="flex items-center gap-3 group">
            <div className="relative">
              {/* Glow effect */}
              <div
                className={cn(
                  "absolute -inset-2 rounded-xl transition-all duration-500",
                  "bg-gradient-to-br from-primary/20 via-primary/10 to-transparent",
                  "opacity-0 group-hover:opacity-100 blur-lg"
                )}
              />
              {/* Icon container */}
              <div
                className={cn(
                  "relative w-10 h-10 rounded-xl flex items-center justify-center",
                  "bg-gradient-to-br from-primary/10 to-primary/5",
                  "border border-primary/20 group-hover:border-primary/40",
                  "transition-all duration-300 group-hover:scale-105"
                )}
              >
                <Dna className="h-5 w-5 text-primary transition-transform duration-500 group-hover:rotate-12" />
              </div>
            </div>
            <div className="hidden sm:block">
              <h1 className="font-serif text-xl tracking-tight text-foreground">
                Medical Deep Research
              </h1>
              <p className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-medium">
                Evidence-Based Analysis
              </p>
            </div>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => {
              const Icon = link.icon;
              const active = isActive(link.href);
              return (
                <Link key={link.href} href={link.href}>
                  <Button
                    variant={link.highlight && !active ? "default" : "ghost"}
                    size="sm"
                    className={cn(
                      "gap-2 transition-all duration-200 btn-press",
                      active && "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
                      link.highlight && !active && "bg-primary hover:bg-primary/90 text-primary-foreground shadow-md shadow-primary/20"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {link.label}
                  </Button>
                </Link>
              );
            })}
          </div>

          {/* Right side: Theme toggle + Mobile menu */}
          <div className="flex items-center gap-2">
            {/* Theme Toggle */}
            {mounted && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className="relative w-9 h-9 rounded-xl hover:bg-muted"
                aria-label="Toggle theme"
              >
                <Sun className="h-[18px] w-[18px] rotate-0 scale-100 transition-all duration-300 dark:-rotate-90 dark:scale-0" />
                <Moon className="absolute h-[18px] w-[18px] rotate-90 scale-0 transition-all duration-300 dark:rotate-0 dark:scale-100" />
              </Button>
            )}

            {/* Mobile Menu Button */}
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden w-9 h-9 rounded-xl"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle menu"
            >
              <div className="relative w-5 h-5">
                <span
                  className={cn(
                    "absolute left-0 w-5 h-0.5 bg-current rounded-full transition-all duration-300",
                    mobileMenuOpen ? "top-[9px] rotate-45" : "top-1"
                  )}
                />
                <span
                  className={cn(
                    "absolute left-0 top-[9px] w-5 h-0.5 bg-current rounded-full transition-all duration-300",
                    mobileMenuOpen ? "opacity-0 scale-0" : "opacity-100"
                  )}
                />
                <span
                  className={cn(
                    "absolute left-0 w-5 h-0.5 bg-current rounded-full transition-all duration-300",
                    mobileMenuOpen ? "top-[9px] -rotate-45" : "top-[17px]"
                  )}
                />
              </div>
            </Button>
          </div>
        </nav>

        {/* Mobile Navigation */}
        <div
          className={cn(
            "md:hidden overflow-hidden transition-all duration-300 ease-out",
            mobileMenuOpen ? "max-h-64 pb-4" : "max-h-0"
          )}
        >
          <div className="flex flex-col gap-1 pt-2 border-t border-border/50">
            {navLinks.map((link, index) => {
              const Icon = link.icon;
              const active = isActive(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setMobileMenuOpen(false)}
                  className="slide-in-right"
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <Button
                    variant={active ? "secondary" : "ghost"}
                    className={cn(
                      "w-full justify-start gap-3 h-11",
                      active && "bg-primary/10 text-primary"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {link.label}
                  </Button>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </header>
  );
}
