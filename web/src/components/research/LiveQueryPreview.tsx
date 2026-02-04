"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { SyntaxHighlightedQuery } from "./QueryDisplay";
import {
  buildPubMedQuery,
  buildPccPubMedQuery,
} from "@/lib/agent/tools";
import { ArrowRight, Sparkles, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface PicoValues {
  population: string;
  intervention: string;
  comparison: string;
  outcome: string;
}

interface PccValues {
  population: string;
  concept: string;
  context: string;
}

interface LiveQueryPreviewProps {
  queryType: "pico" | "pcc";
  picoValues?: PicoValues;
  pccValues?: PccValues;
  debounceMs?: number;
  className?: string;
}

export function LiveQueryPreview({
  queryType,
  picoValues,
  pccValues,
  debounceMs = 300,
  className,
}: LiveQueryPreviewProps) {
  const [generatedQuery, setGeneratedQuery] = useState<string>("");
  const [meshTerms, setMeshTerms] = useState<string[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const isMountedRef = useRef(true);

  // Track mounted state to prevent memory leaks
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Determine if we have enough input to generate a query
  const hasInput = useMemo(() => {
    if (queryType === "pico" && picoValues) {
      return !!(
        picoValues.population?.trim() ||
        picoValues.intervention?.trim() ||
        picoValues.outcome?.trim()
      );
    }
    if (queryType === "pcc" && pccValues) {
      return !!(
        pccValues.population?.trim() ||
        pccValues.concept?.trim() ||
        pccValues.context?.trim()
      );
    }
    return false;
  }, [queryType, picoValues, pccValues]);

  // Debounced effect for query generation
  useEffect(() => {
    if (!hasInput) {
      setGeneratedQuery("");
      setMeshTerms([]);
      return;
    }

    setIsGenerating(true);

    const timer = setTimeout(() => {
      // Check if still mounted before updating state
      if (!isMountedRef.current) return;

      try {
        if (queryType === "pico" && picoValues) {
          const result = buildPubMedQuery({
            population: picoValues.population || "",
            intervention: picoValues.intervention || "",
            comparison: picoValues.comparison || undefined,
            outcome: picoValues.outcome || "",
          });
          if (isMountedRef.current) {
            setGeneratedQuery(result.formattedQuery);
            setMeshTerms(result.meshTerms);
          }
        } else if (queryType === "pcc" && pccValues) {
          const result = buildPccPubMedQuery({
            population: pccValues.population || "",
            concept: pccValues.concept || "",
            context: pccValues.context || "",
          });
          if (isMountedRef.current) {
            setGeneratedQuery(result.formattedQuery);
            setMeshTerms(result.meshTerms);
          }
        }
      } catch (error) {
        console.error("Error generating query:", error);
        if (isMountedRef.current) {
          setGeneratedQuery("");
          setMeshTerms([]);
        }
      } finally {
        if (isMountedRef.current) {
          setIsGenerating(false);
        }
      }
    }, debounceMs);

    return () => clearTimeout(timer);
  }, [queryType, picoValues, pccValues, hasInput, debounceMs]);

  // Don't render if no input
  if (!hasInput && !generatedQuery) {
    return null;
  }

  return (
    <Card
      className={cn(
        "overflow-hidden animate-fade-in border-dashed",
        className
      )}
    >
      <CardContent className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2 text-sm">
          <ArrowRight className="h-4 w-4 text-primary shrink-0" />
          <span className="font-medium">Live Query Preview</span>
          {isGenerating && (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-auto" />
          )}
          {!isGenerating && generatedQuery && (
            <Sparkles className="h-3 w-3 text-amber-500 ml-auto" />
          )}
        </div>

        {/* Query Display */}
        {isGenerating ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : generatedQuery ? (
          <div className="bg-muted/30 border rounded-lg p-3 overflow-x-auto max-h-[200px]">
            <SyntaxHighlightedQuery query={generatedQuery} className="text-xs leading-relaxed" />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground italic">
            Start typing to generate a query...
          </p>
        )}

        {/* MeSH Terms */}
        {!isGenerating && meshTerms.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">MeSH:</span>
            {meshTerms.slice(0, 5).map((term, i) => (
              <Badge
                key={i}
                variant="secondary"
                className="text-[10px] font-normal text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-950/30"
              >
                {term}
              </Badge>
            ))}
            {meshTerms.length > 5 && (
              <span className="text-[10px] text-muted-foreground">
                +{meshTerms.length - 5} more
              </span>
            )}
          </div>
        )}

        {/* Legend hint */}
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          <span className="text-green-600 dark:text-green-400">[MeSH]</span>
          <span className="text-blue-600 dark:text-blue-400">[tiab]</span>
          <span className="text-orange-600 dark:text-orange-400">AND/OR</span>
        </div>
      </CardContent>
    </Card>
  );
}
