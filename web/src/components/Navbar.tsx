"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Settings, FlaskConical, Plus, Key } from "lucide-react";

export function Navbar() {
  return (
    <nav className="border-b bg-background">
      <div className="container mx-auto px-4 h-16 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/research" className="flex items-center gap-2">
            <FlaskConical className="h-6 w-6 text-primary" />
            <span className="font-bold text-lg">Medical Deep Research</span>
          </Link>
          <div className="hidden md:flex items-center gap-4">
            <Link href="/research">
              <Button variant="ghost" size="sm">
                Research
              </Button>
            </Link>
            <Link href="/research/new">
              <Button variant="ghost" size="sm">
                <Plus className="h-4 w-4 mr-1" />
                New
              </Button>
            </Link>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link href="/settings/api-keys">
            <Button variant="ghost" size="sm">
              <Key className="h-4 w-4 mr-1" />
              API Keys
            </Button>
          </Link>
          <Link href="/settings">
            <Button variant="ghost" size="icon">
              <Settings className="h-5 w-5" />
            </Button>
          </Link>
        </div>
      </div>
    </nav>
  );
}
