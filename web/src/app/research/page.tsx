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
import { useTranslations } from "@/i18n/client";

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
  const { t } = useTranslations("research");

  return (
    <Card className="border-dashed border-2 bg-gradient-to-br from-muted/30 to-transparent">
      <CardContent className="py-20 text-center">
        <div className="mx-auto mb-8 relative w-24 h-24">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/20 to-primary/5 rounded-full animate-pulse" />
          <div className="absolute inset-3 bg-background rounded-full flex items-center justify-center shadow-inner">
            <Beaker className="h-10 w-10 text-primary" />
          </div>
        </div>
        <h3 className="font-serif text-2xl mb-3">
          {t("noResearchYet")}
        </h3>
        <p className="text-muted-foreground mb-8 max-w-md mx-auto">
          {t("noResearchDescription")}
        </p>
        <Link href="/research/new">
          <Button size="lg" className="gap-2 shadow-lg shadow-primary/20">
            <Plus className="h-4 w-4" />
            {t("startNewResearch")}
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslations("status");

  const config: Record<
    string,
    { className: string; labelKey: string; pulse?: boolean }
  > = {
    pending: { className: "status-pending", labelKey: "pending" },
    running: { className: "status-running", labelKey: "running", pulse: true },
    completed: { className: "status-completed", labelKey: "completed" },
    failed: { className: "status-failed", labelKey: "failed" },
    cancelled: { className: "status-pending", labelKey: "cancelled" },
  };

  const { className, labelKey, pulse } = config[status] || config.pending;

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
      <span className="relative">{t(labelKey)}</span>
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
  const { t } = useTranslations("research");

  return (
    <div className="space-y-8 stagger-fade">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl sm:text-4xl tracking-tight">
            {t("history")}
          </h1>
          <p className="text-muted-foreground mt-2">
            {t("historyDescription")}
          </p>
        </div>
        <Link href="/research/new">
          <Button size="lg" className="gap-2 shadow-lg shadow-primary/25 bg-gradient-to-r from-primary to-primary/90 hover:from-primary/90 hover:to-primary">
            <Plus className="h-4 w-4" />
            {t("newResearch")}
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
              {t("loadError")}
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
                  "group overflow-hidden cursor-pointer transition-all duration-300",
                  "border-l-4 hover:-translate-y-0.5 hover:shadow-lg",
                  item.status === "completed" && "border-l-[hsl(var(--status-completed))]",
                  item.status === "running" && "border-l-[hsl(var(--status-running))]",
                  item.status === "failed" && "border-l-[hsl(var(--status-failed))]",
                  item.status === "pending" && "border-l-[hsl(var(--status-pending))]"
                )}
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <QueryTypeBadge type={item.queryType} />
                      </div>
                      <CardTitle className="text-base font-sans font-medium line-clamp-2 group-hover:text-primary transition-colors">
                        {item.query}
                      </CardTitle>
                      <CardDescription className="mt-2 flex items-center gap-1.5 text-xs">
                        <Clock className="h-3.5 w-3.5" />
                        {formatDate(new Date(item.createdAt))}
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={item.status} />
                      <div className="p-2 rounded-lg bg-muted opacity-0 group-hover:opacity-100 transition-opacity">
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>{t("progress")}</span>
                      <span className="font-semibold text-foreground">{item.progress}%</span>
                    </div>
                    <Progress
                      value={item.progress}
                      className={cn(
                        "h-1.5",
                        item.status === "running" && "progress-shimmer"
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
