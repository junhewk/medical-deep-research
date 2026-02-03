"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { LogOut, Settings, FlaskConical, Plus } from "lucide-react";

interface NavbarProps {
  username: string;
}

export function Navbar({ username }: NavbarProps) {
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  }

  return (
    <nav className="border-b bg-white">
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

        <div className="flex items-center gap-4">
          <span className="text-sm text-muted-foreground hidden sm:block">
            {username}
          </span>
          <Link href="/settings">
            <Button variant="ghost" size="icon">
              <Settings className="h-5 w-5" />
            </Button>
          </Link>
          <Button variant="ghost" size="icon" onClick={handleLogout}>
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </nav>
  );
}
