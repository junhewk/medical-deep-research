"use client";

import Link from "next/link";
import { useResearchList } from "@/lib/research";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Plus, Loader2, FileText } from "lucide-react";
import { formatDate } from "@/lib/utils";

export default function ResearchListPage() {
  const { data: research, isLoading, error } = useResearchList();

  const statusColors = {
    pending: "secondary",
    running: "default",
    completed: "success",
    failed: "destructive",
  } as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Research History</h1>
          <p className="text-muted-foreground">
            View and manage your medical research queries
          </p>
        </div>
        <Link href="/research/new">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            New Research
          </Button>
        </Link>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Failed to load research history. Please try again.
            </p>
          </CardContent>
        </Card>
      )}

      {research && research.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium mb-2">No research yet</h3>
            <p className="text-muted-foreground mb-4">
              Start your first medical research query
            </p>
            <Link href="/research/new">
              <Button>
                <Plus className="h-4 w-4 mr-2" />
                New Research
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {research && research.length > 0 && (
        <div className="grid gap-4">
          {research.map((item) => (
            <Link key={item.id} href={`/research/${item.id}`}>
              <Card className="hover:bg-muted/50 transition-colors cursor-pointer">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-base truncate">
                        {item.query}
                      </CardTitle>
                      <CardDescription className="mt-1">
                        {formatDate(new Date(item.createdAt))}
                      </CardDescription>
                    </div>
                    <Badge variant={statusColors[item.status as keyof typeof statusColors] || "secondary"}>
                      {item.status}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Progress</span>
                      <span>{item.progress}%</span>
                    </div>
                    <Progress value={item.progress} className="h-1" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
