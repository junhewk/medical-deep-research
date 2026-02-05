import { z } from "zod";
import { tool } from "@langchain/core/tools";

const SCOPUS_BASE_URL = "https://api.elsevier.com/content/search/scopus";

/**
 * Convert PubMed query syntax to Scopus query syntax
 *
 * PubMed uses tags like [tiab], [mh], [pt] while Scopus uses TITLE-ABS-KEY(), KEY(), DOCTYPE()
 *
 * Examples:
 * - "heart attack[tiab]" → TITLE-ABS-KEY("heart attack")
 * - "myocardial infarction[mh]" → KEY("myocardial infarction")
 * - "randomized controlled trial[pt]" → DOCTYPE(ar)
 */
export function convertToScopusQuery(pubmedQuery: string): string {
  if (!pubmedQuery?.trim()) return "";

  // Remove all PubMed field tags: [tiab], [mh], [pt], [tw], [majr], [mesh], [all]
  const query = pubmedQuery
    .replace(/\[(tiab|mh|pt|tw|majr|mesh|all)\]/gi, "")
    .replace(/\s+/g, " ")
    .trim();

  const terms = extractKeyTerms(query);
  if (terms.length === 0) return "";

  // Quote multi-word terms for Scopus
  const scopusTerms = terms.map(term => term.includes(" ") ? `"${term}"` : term);

  return `TITLE-ABS-KEY(${scopusTerms.join(" AND ")})`;
}

const STOP_WORDS = new Set(["and", "or", "not", "the", "for", "with", "none"]);

function isValidTerm(term: string): boolean {
  const cleaned = term.trim().toLowerCase();
  return cleaned.length > 2 && !STOP_WORDS.has(cleaned);
}

/**
 * Extract key terms from a query string, preserving quoted phrases
 */
function extractKeyTerms(query: string): string[] {
  const terms: string[] = [];
  const seenLower = new Set<string>();

  // Extract quoted phrases first
  const quotedPhrases = query.match(/"[^"]+"/g) || [];
  for (const phrase of quotedPhrases) {
    const cleanPhrase = phrase.replace(/"/g, "").trim();
    if (cleanPhrase && !seenLower.has(cleanPhrase.toLowerCase())) {
      terms.push(cleanPhrase);
      seenLower.add(cleanPhrase.toLowerCase());
    }
  }

  // Remove quoted phrases and boolean operators, then extract individual terms
  const remaining = query
    .replace(/"[^"]+"/g, "")
    .replace(/\b(AND|OR|NOT)\b/gi, " ")
    .replace(/[()]/g, " ");

  for (const word of remaining.split(/\s+/)) {
    const cleaned = word.trim();
    if (cleaned && isValidTerm(cleaned) && !seenLower.has(cleaned.toLowerCase())) {
      terms.push(cleaned);
      seenLower.add(cleaned.toLowerCase());
    }
  }

  return terms;
}

/**
 * Build a native Scopus query from PICO components
 *
 * This creates an optimized Scopus query directly from PICO structure
 * without going through PubMed syntax
 */
export interface PICOComponents {
  population?: string;
  intervention?: string;
  comparison?: string;
  outcome?: string;
}

function buildComponentClause(value: string | undefined, skipValues: string[] = []): string | null {
  if (!value?.trim()) return null;
  if (skipValues.some(skip => value.toLowerCase() === skip)) return null;

  const terms = extractMedicalTerms(value);
  if (terms.length === 0) return null;

  return `(${terms.map(t => `"${t}"`).join(" OR ")})`;
}

export function buildScopusQueryFromPICO(pico: PICOComponents): string {
  const parts = [
    buildComponentClause(pico.population),
    buildComponentClause(pico.intervention),
    buildComponentClause(pico.comparison, ["none"]),
    buildComponentClause(pico.outcome),
  ].filter((part): part is string => part !== null);

  if (parts.length === 0) return "";

  return `TITLE-ABS-KEY(${parts.join(" AND ")})`;
}

/**
 * Extract medical terms from a PICO component string
 * Handles comma-separated lists and common medical phrases
 */
function extractMedicalTerms(input: string): string[] {
  if (!input) return [];

  return input
    .split(/[,;]|\bOR\b/i)
    .map(part => part.replace(/^\s*-\s*/, "").replace(/[()]/g, "").trim())
    .filter(isValidTerm);
}

export interface ScopusArticle {
  scopusId: string;
  title: string;
  abstract?: string;
  authors: string[];
  journal: string;
  publicationDate: string;
  doi?: string;
  citationCount: number;
  url: string;
}

interface ScopusSearchResponse {
  "search-results": {
    "opensearch:totalResults": string;
    entry?: Array<{
      "dc:identifier": string;
      "dc:title": string;
      "dc:description"?: string;
      "dc:creator"?: string;
      "prism:publicationName": string;
      "prism:coverDate": string;
      "prism:doi"?: string;
      "citedby-count"?: string;
      link?: Array<{
        "@ref": string;
        "@href": string;
      }>;
    }>;
  };
}

export type ScopusSortBy = "relevancy" | "citedby-count" | "pubyear" | "coverDate";

async function searchScopus(
  query: string,
  maxResults: number = 20,
  apiKey: string,
  sortBy: ScopusSortBy = "citedby-count"
): Promise<ScopusArticle[]> {
  const params = new URLSearchParams({
    query: query,
    count: maxResults.toString(),
    sort: sortBy,
    view: "COMPLETE",
  });

  const response = await fetch(`${SCOPUS_BASE_URL}?${params}`, {
    headers: {
      "X-ELS-APIKey": apiKey,
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("Invalid Scopus API key");
    }
    throw new Error(`Scopus search failed: ${response.statusText}`);
  }

  const data = (await response.json()) as ScopusSearchResponse;
  const entries = data["search-results"].entry || [];

  return entries.map((entry) => {
    const scopusLink = entry.link?.find((l) => l["@ref"] === "scopus")?.["@href"];

    return {
      scopusId: entry["dc:identifier"].replace("SCOPUS_ID:", ""),
      title: entry["dc:title"],
      abstract: entry["dc:description"],
      authors: entry["dc:creator"] ? [entry["dc:creator"]] : [],
      journal: entry["prism:publicationName"],
      publicationDate: entry["prism:coverDate"],
      doi: entry["prism:doi"],
      citationCount: parseInt(entry["citedby-count"] || "0", 10),
      url: scopusLink || `https://www.scopus.com/record/display.uri?eid=${entry["dc:identifier"]}`,
    };
  });
}

export const scopusSearchTool = tool(
  async ({ query, maxResults, apiKey, sortBy }) => {
    if (!apiKey) {
      return JSON.stringify({
        success: false,
        error: "Scopus API key is required. Please configure it in Settings > API Keys.",
      });
    }

    try {
      const articles = await searchScopus(
        query,
        maxResults || 20,
        apiKey,
        (sortBy as ScopusSortBy) || "citedby-count"
      );

      return JSON.stringify({
        success: true,
        count: articles.length,
        sortedBy: sortBy || "citedby-count",
        articles: articles.map((a) => ({
          scopusId: a.scopusId,
          title: a.title,
          // CRITICAL: Return FULL abstract to prevent hallucination from incomplete data
          abstract: a.abstract || null,
          authors: a.authors.join(", "),
          journal: a.journal,
          publicationDate: a.publicationDate,
          doi: a.doi,
          citationCount: a.citationCount,
          url: a.url,
        })),
      });
    } catch (error) {
      return JSON.stringify({
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },
  {
    name: "scopus_search",
    description:
      "Searches Scopus database for scientific literature. Requires Scopus API key (BYOK). Supports complex queries with AND, OR, NOT operators. By default sorts by citation count.",
    schema: z.object({
      query: z.string().describe("Scopus search query"),
      maxResults: z.number().optional().nullable().default(20).describe("Maximum number of results"),
      apiKey: z.string().describe("Scopus/Elsevier API key"),
      sortBy: z.enum(["relevancy", "citedby-count", "pubyear", "coverDate"])
        .optional()
        .nullable()
        .default("citedby-count")
        .describe("Sort order: citedby-count (default), relevancy, pubyear, coverDate"),
    }),
  }
);

export { searchScopus };
