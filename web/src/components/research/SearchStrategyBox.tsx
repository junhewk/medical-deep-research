"use client";

import type { ToolExecution } from "@/lib/research";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { QueryDisplayInline } from "./QueryDisplay";
import {
  Search,
  CheckCircle,
  XCircle,
  Clock,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslations } from "@/i18n/client";

interface SearchStrategyBoxProps {
  executions: ToolExecution[];
}

const SEARCH_TOOLS = new Set([
  "pubmed_search",
  "scopus_search",
  "cochrane_search",
  "openalex_search",
  "semantic_scholar_search",
]);

const DB_CONFIG: Record<string, { name: string; colorVar: string }> = {
  pubmed_search: { name: "PubMed", colorVar: "--pico-p" },
  scopus_search: { name: "Scopus", colorVar: "--pico-o" },
  cochrane_search: { name: "Cochrane Library", colorVar: "--pico-c" },
  openalex_search: { name: "OpenAlex", colorVar: "--pico-i" },
  semantic_scholar_search: { name: "Semantic Scholar", colorVar: "--primary" },
};

// PubMed queries use boolean syntax that benefits from highlighting
function isPubMedLikeQuery(tool: string): boolean {
  return tool === "pubmed_search" || tool === "cochrane_search";
}

export function SearchStrategyBox({ executions }: SearchStrategyBoxProps) {
  const { t } = useTranslations();

  const searchExecutions = executions.filter((e) => SEARCH_TOOLS.has(e.tool));
  if (searchExecutions.length === 0) return null;

  const totalArticles = searchExecutions.reduce(
    (sum, e) => sum + (e.resultCount ?? 0),
    0
  );
  const hasAnyResults = searchExecutions.some((e) => e.resultCount !== undefined);

  return (
    <Card className="card-hover overflow-hidden">
      <CardHeader className="border-b border-border/50 bg-gradient-to-r from-primary/5 to-transparent">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <Search className="h-4 w-4 text-primary" />
            </div>
            {t("progress.searchStrategy")}
          </CardTitle>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span>{searchExecutions.length} {t("progress.databases")}</span>
            {hasAnyResults && (
              <>
                <span className="text-border">|</span>
                <span className="font-semibold text-foreground">
                  {totalArticles} {t("progress.articlesFound")}
                </span>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-6">
        <div className="space-y-3">
          {searchExecutions.map((exec, index) => {
            const config = DB_CONFIG[exec.tool] || {
              name: exec.tool,
              colorVar: "--muted-foreground",
            };

            return (
              <div
                key={index}
                className={cn(
                  "p-4 rounded-lg border transition-all",
                  exec.status === "failed"
                    ? "bg-[hsl(var(--status-failed))]/5 border-[hsl(var(--status-failed))]/20"
                    : "bg-muted/30 border-border/50"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className="text-xs font-semibold border"
                      style={{
                        backgroundColor: `hsl(var(${config.colorVar}) / 0.1)`,
                        color: `hsl(var(${config.colorVar}))`,
                        borderColor: `hsl(var(${config.colorVar}) / 0.25)`,
                      }}
                    >
                      {config.name}
                    </Badge>
                    {exec.status === "completed" ? (
                      <CheckCircle className="h-3.5 w-3.5 text-[hsl(var(--status-completed))]" />
                    ) : exec.status === "failed" ? (
                      <XCircle className="h-3.5 w-3.5 text-[hsl(var(--status-failed))]" />
                    ) : null}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {exec.resultCount !== undefined && (
                      <span className="flex items-center gap-1">
                        <FileText className="h-3 w-3" />
                        {exec.resultCount} {t("progress.articlesFound")}
                      </span>
                    )}
                    {exec.duration !== undefined && (
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {exec.duration.toFixed(1)}s
                      </span>
                    )}
                  </div>
                </div>
                {exec.query && (
                  <div className="mt-2">
                    {isPubMedLikeQuery(exec.tool) ? (
                      <QueryDisplayInline query={exec.query} />
                    ) : (
                      <div className="p-2.5 rounded-md bg-background/80 border border-border/30">
                        <p className="text-xs font-mono text-muted-foreground break-all leading-relaxed">
                          {exec.query}
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {exec.error && (
                  <p className="text-xs text-[hsl(var(--status-failed))] mt-2 font-medium">
                    {exec.error}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
