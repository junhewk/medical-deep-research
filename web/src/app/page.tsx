import { validateRequest } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default async function HomePage() {
  const { user } = await validateRequest();

  if (user) {
    redirect("/research");
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <Card className="w-full max-w-lg mx-4">
        <CardHeader className="text-center">
          <CardTitle className="text-3xl font-bold text-primary">
            Medical Deep Research
          </CardTitle>
          <CardDescription className="text-lg mt-2">
            Evidence-Based Medical Research Assistant
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="text-center text-muted-foreground">
            <p>Powered by AI with PICO framework support,</p>
            <p>MeSH term mapping, and evidence classification.</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Link href="/auth/login" className="w-full">
              <Button variant="default" className="w-full" size="lg">
                Sign In
              </Button>
            </Link>
            <Link href="/auth/register" className="w-full">
              <Button variant="outline" className="w-full" size="lg">
                Register
              </Button>
            </Link>
          </div>

          <div className="border-t pt-4">
            <h3 className="font-semibold mb-2">Key Features</h3>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>• Deep Agent architecture for autonomous research</li>
              <li>• PICO query builder for clinical questions</li>
              <li>• MeSH term mapping (60+ medical terms)</li>
              <li>• Evidence level classification (I-V)</li>
              <li>• Real-time progress tracking</li>
            </ul>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
