"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  parseQueryForHighlighting,
  getTokenColorClass,
  type QueryBlock,
} from "@/lib/agent/tools/client";
import { Copy, Check, Search, Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface QueryDisplayProps {
  query: string;
  formattedQuery?: string;
  queryBlocks?: QueryBlock[];
  meshTerms?: string[];
  title?: string;
  showLegend?: boolean;
  className?: string;
}

function QueryLegend() {
  const items = [
    { type: "mesh", label: "[MeSH]", desc: "MeSH controlled vocabulary term" },
    { type: "tiab", label: "[tiab]", desc: "Title and abstract search" },
    { type: "pt", label: "[pt]", desc: "Publication type filter" },
    { type: "dp", label: "[dp]", desc: "Date of publication" },
    { type: "operator", label: "AND/OR", desc: "Boolean operators" },
  ] as const;

  return (
    <div className="flex flex-wrap gap-2 text-xs">
      {items.map((item) => (
        <TooltipProvider key={item.type}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className={cn(
                  "px-1.5 py-0.5 rounded bg-muted/50 cursor-help",
                  getTokenColorClass(item.type)
                )}
              >
                {item.label}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p>{item.desc}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ))}
    </div>
  );
}

export function SyntaxHighlightedQuery({ query, className }: { query: string; className?: string }) {
  const tokens = parseQueryForHighlighting(query);

  return (
    <code className={cn("font-mono whitespace-pre-wrap break-all", className)}>
      {tokens.map((token, i) => (
        <span key={i} className={getTokenColorClass(token.type)}>
          {token.text}
        </span>
      ))}
    </code>
  );
}

export function QueryDisplay({
  query,
  formattedQuery,
  queryBlocks,
  meshTerms,
  title = "Generated Query",
  showLegend = true,
  className,
}: QueryDisplayProps) {
  const [copied, setCopied] = useState(false);

  const displayQuery = formattedQuery || query;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(query);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Search className="h-4 w-4 text-primary" />
            {title}
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="h-8 px-2"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 mr-1 text-green-600" />
                <span className="text-xs">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5 mr-1" />
                <span className="text-xs">Copy</span>
              </>
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Syntax Highlighted Query */}
        <div className="relative">
          <div className="bg-muted/50 border rounded-lg p-4 overflow-x-auto max-h-[300px]">
            <SyntaxHighlightedQuery query={displayQuery} className="text-sm" />
          </div>
        </div>

        {/* Query Blocks */}
        {queryBlocks && queryBlocks.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <Info className="h-3 w-3" />
              Query Components
            </p>
            <div className="grid gap-2">
              {queryBlocks.map((block, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-xs p-2 bg-muted/30 rounded"
                >
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] shrink-0",
                      block.concept === "P" && "border-pico-p text-pico-p",
                      block.concept === "I" && "border-pico-i text-pico-i",
                      block.concept === "C" && "border-pico-c text-pico-c",
                      block.concept === "O" && "border-pico-o text-pico-o",
                      block.concept === "Concept" && "border-pico-c text-pico-c",
                      block.concept === "Context" && "border-pico-o text-pico-o"
                    )}
                  >
                    {block.concept}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium">{block.label}: </span>
                    <code className="text-muted-foreground break-all">
                      {block.combined || "—"}
                    </code>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MeSH Terms */}
        {meshTerms && meshTerms.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">
              MeSH Terms Identified
            </p>
            <div className="flex flex-wrap gap-1.5">
              {meshTerms.map((term, i) => (
                <Badge
                  key={i}
                  variant="secondary"
                  className="text-xs font-normal text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30"
                >
                  {term}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Legend */}
        {showLegend && (
          <div className="pt-2 border-t">
            <QueryLegend />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Compact version for inline display
 */
export function QueryDisplayInline({
  query,
  className,
}: {
  query: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(query);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  return (
    <div className={cn("relative group", className)}>
      <div className="bg-muted/50 border rounded-lg p-3 overflow-x-auto">
        <SyntaxHighlightedQuery query={query} />
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={handleCopy}
        className="absolute top-2 right-2 h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-600" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </Button>
    </div>
  );
}
