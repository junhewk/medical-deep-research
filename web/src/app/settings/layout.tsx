import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Key } from "lucide-react";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6 max-w-4xl">
        <div className="mb-6">
          <Link href="/research">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Research
            </Button>
          </Link>
        </div>

        <div className="flex gap-6">
          {/* Sidebar */}
          <nav className="w-48 flex-shrink-0">
            <div className="space-y-1">
              <Link href="/settings/api-keys">
                <Button variant="ghost" className="w-full justify-start">
                  <Key className="h-4 w-4 mr-2" />
                  API Keys
                </Button>
              </Link>
            </div>
          </nav>

          {/* Main content */}
          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </div>
    </div>
  );
}
