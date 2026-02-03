"use client";

import { useResearch } from "@/lib/research";
import { ResearchProgressView } from "@/components/research/ResearchProgress";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";

interface ResearchPageProps {
  params: { id: string };
}

export default function ResearchPage({ params }: ResearchPageProps) {
  const { data, isLoading, error } = useResearch(params.id);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link href="/research">
          <Button variant="ghost">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Research
          </Button>
        </Link>
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Failed to load research. The research may not exist or you may not
              have permission to view it.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <Link href="/research">
          <Button variant="ghost">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Research
          </Button>
        </Link>
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground">Research not found.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Link href="/research">
        <Button variant="ghost">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Research
        </Button>
      </Link>

      <ResearchProgressView data={data} />
    </div>
  );
}
