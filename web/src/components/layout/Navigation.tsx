"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Microscope,
  Plus,
  Key,
  Sun,
  Moon,
  Menu,
  X,
  FileText,
  Home,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/research", label: "Research", icon: FileText },
  { href: "/research/new", label: "New Query", icon: Plus },
  { href: "/settings/api-keys", label: "API Keys", icon: Key },
];

export function Navigation() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const isActive = (href: string) => {
    if (href === "/research") {
      return pathname === "/research" || pathname === "/";
    }
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md">
      <div className="container">
        <nav className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link
            href="/research"
            className="flex items-center gap-3 group"
          >
            <div className="relative">
              <div className="absolute -inset-2 bg-primary/10 rounded-full blur-md group-hover:bg-primary/20 transition-colors" />
              <Microscope className="relative h-7 w-7 text-primary" />
            </div>
            <div className="hidden sm:block">
              <span className="font-serif text-xl font-semibold tracking-tight">
                Medical Deep Research
              </span>
              <span className="hidden lg:inline text-xs text-muted-foreground ml-2 font-normal">
                v2.0
              </span>
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
                    variant={active ? "secondary" : "ghost"}
                    size="sm"
                    className={cn(
                      "gap-2 transition-all duration-200",
                      active && "bg-primary/10 text-primary hover:bg-primary/15"
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
                className="relative"
                aria-label="Toggle theme"
              >
                <Sun className="h-5 w-5 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
                <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
              </Button>
            )}

            {/* Mobile Menu Button */}
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? (
                <X className="h-5 w-5" />
              ) : (
                <Menu className="h-5 w-5" />
              )}
            </Button>
          </div>
        </nav>

        {/* Mobile Navigation */}
        {mobileMenuOpen && (
          <div className="md:hidden border-t border-border/50 py-4 animate-fade-in">
            <div className="flex flex-col gap-2">
              {navLinks.map((link) => {
                const Icon = link.icon;
                const active = isActive(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={() => setMobileMenuOpen(false)}
                  >
                    <Button
                      variant={active ? "secondary" : "ghost"}
                      className={cn(
                        "w-full justify-start gap-3",
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
        )}
      </div>
    </header>
  );
}
