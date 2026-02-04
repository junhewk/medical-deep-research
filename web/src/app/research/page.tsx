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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Plus,
  FileText,
  BookOpen,
  Beaker,
  Clock,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { formatDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

function ResearchSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <Card key={i} className="overflow-hidden">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-5 w-16" />
                </div>
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-1/3" />
              </div>
              <Skeleton className="h-6 w-20" />
            </div>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-2 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <div className="mx-auto mb-6 relative w-20 h-20">
          <div className="absolute inset-0 bg-primary/10 rounded-full animate-pulse" />
          <div className="absolute inset-2 bg-primary/5 rounded-full flex items-center justify-center">
            <Beaker className="h-8 w-8 text-primary" />
          </div>
        </div>
        <h3 className="font-serif text-xl font-semibold mb-2">
          No research yet
        </h3>
        <p className="text-muted-foreground mb-6 max-w-sm mx-auto">
          Start your first evidence-based medical research query using the PICO
          or PCC framework
        </p>
        <Link href="/research/new">
          <Button size="lg" className="gap-2">
            <Plus className="h-4 w-4" />
            Start New Research
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    { className: string; label: string; pulse?: boolean }
  > = {
    pending: { className: "status-pending", label: "Pending" },
    running: { className: "status-running", label: "Running", pulse: true },
    completed: { className: "status-completed", label: "Completed" },
    failed: { className: "status-failed", label: "Failed" },
    cancelled: { className: "status-pending", label: "Cancelled" },
  };

  const { className, label, pulse } = config[status] || config.pending;

  return (
    <Badge
      variant="outline"
      className={cn(
        className,
        "border font-medium",
        pulse && "relative overflow-hidden"
      )}
    >
      {pulse && (
        <span className="absolute inset-0 bg-status-running/20 animate-pulse" />
      )}
      <span className="relative">{label}</span>
    </Badge>
  );
}

function QueryTypeBadge({ type }: { type?: string }) {
  if (!type) return null;

  const config: Record<string, { icon: typeof BookOpen; color: string }> = {
    pico: { icon: BookOpen, color: "text-pico-p border-pico-p/30 bg-pico-p/10" },
    pcc: { icon: FileText, color: "text-pico-c border-pico-c/30 bg-pico-c/10" },
    free: {
      icon: Sparkles,
      color: "text-accent border-accent/30 bg-accent/10",
    },
  };

  const { icon: Icon, color } = config[type] || config.free;

  return (
    <Badge variant="outline" className={cn("text-xs font-medium border", color)}>
      <Icon className="h-3 w-3 mr-1" />
      {type.toUpperCase()}
    </Badge>
  );
}

export default function ResearchListPage() {
  const { data: research, isLoading, error } = useResearchList();

  return (
    <div className="space-y-8 fade-in-stagger">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">
            Research History
          </h1>
          <p className="text-muted-foreground mt-1">
            View and manage your medical research queries
          </p>
        </div>
        <Link href="/research/new">
          <Button size="lg" className="gap-2 shadow-lg shadow-primary/20">
            <Plus className="h-4 w-4" />
            New Research
          </Button>
        </Link>
      </div>

      {/* Loading State */}
      {isLoading && <ResearchSkeleton />}

      {/* Error State */}
      {error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-6">
            <p className="text-destructive">
              Failed to load research history. Please try again.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Empty State */}
      {research && research.length === 0 && <EmptyState />}

      {/* Research List */}
      {research && research.length > 0 && (
        <div className="grid gap-4">
          {research.map((item, index) => (
            <Link key={item.id} href={`/research/${item.id}`}>
              <Card
                className={cn(
                  "group overflow-hidden card-hover cursor-pointer",
                  "border-l-4",
                  item.status === "completed" && "border-l-status-completed",
                  item.status === "running" && "border-l-status-running",
                  item.status === "failed" && "border-l-status-failed",
                  item.status === "pending" && "border-l-status-pending"
                )}
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <QueryTypeBadge type={item.queryType} />
                      </div>
                      <CardTitle className="text-base font-medium line-clamp-2 group-hover:text-primary transition-colors">
                        {item.query}
                      </CardTitle>
                      <CardDescription className="mt-1 flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatDate(new Date(item.createdAt))}
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={item.status} />
                      <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Progress</span>
                      <span className="font-medium">{item.progress}%</span>
                    </div>
                    <Progress
                      value={item.progress}
                      className={cn(
                        "h-1.5",
                        item.status === "running" && "progress-animated"
                      )}
                    />
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
