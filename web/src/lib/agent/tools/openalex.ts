import { z } from "zod";
import { tool } from "@langchain/core/tools";

const OPENALEX_BASE_URL = "https://api.openalex.org/works";
const POLITE_EMAIL = "medical-deep-research@users.noreply.github.com";

/**
 * Reconstruct abstract text from OpenAlex inverted index format.
 *
 * OpenAlex stores abstracts as { word: [position, ...] } maps.
 * We rebuild them into plain text by sorting positions.
 */
export function reconstructAbstract(
  invertedIndex: Record<string, number[]> | null | undefined
): string | undefined {
  if (!invertedIndex || typeof invertedIndex !== "object") return undefined;

  const words: [number, string][] = [];
  for (const [word, positions] of Object.entries(invertedIndex)) {
    if (!Array.isArray(positions)) continue;
    for (const pos of positions) {
      words.push([pos, word]);
    }
  }

  if (words.length === 0) return undefined;

  words.sort((a, b) => a[0] - b[0]);
  return words.map(([, w]) => w).join(" ");
}

/**
 * Infer evidence level from OpenAlex work type and title keywords
 */
function inferEvidenceLevel(
  type?: string,
  title?: string
): string | undefined {
  const t = title?.toLowerCase() ?? "";

  if (/systematic\s*review|meta[\s-]?analysis/.test(t)) return "Level I";
  if (/randomized|randomised|rct\b/.test(t)) return "Level II";
  if (/cohort|case[\s-]?control|prospective|retrospective/.test(t)) return "Level III";
  if (/case\s*(series|report)/.test(t)) return "Level IV";

  // Fallback on OpenAlex type
  if (type === "review") return "Level I";

  return undefined;
}

export interface OpenAlexArticle {
  openalexId: string;
  title: string;
  abstract?: string;
  authors: string[];
  journal: string;
  publicationDate: string;
  publicationYear: string;
  doi?: string;
  pmid?: string;
  citationCount: number;
  url: string;
  evidenceLevel?: string;
}

interface OpenAlexWork {
  id: string;
  title?: string;
  abstract_inverted_index?: Record<string, number[]>;
  authorships?: Array<{
    author?: { display_name?: string };
  }>;
  primary_location?: {
    source?: { display_name?: string };
  };
  publication_date?: string;
  publication_year?: number;
  doi?: string;
  ids?: {
    pmid?: string;
    doi?: string;
  };
  cited_by_count?: number;
  type?: string;
}

interface OpenAlexResponse {
  results?: OpenAlexWork[];
  meta?: {
    count?: number;
  };
}

async function fetchWithRetry(
  url: string,
  maxRetries: number = 3
): Promise<Response> {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": `MedicalDeepResearch/1.0 (mailto:${POLITE_EMAIL})`,
        Accept: "application/json",
      },
    });

    if (response.ok) return response;

    if (response.status === 429 && attempt < maxRetries) {
      const delay = Math.pow(2, attempt) * 1000;
      console.log(`[OpenAlex] Rate limited, retrying in ${delay}ms...`);
      await new Promise((resolve) => setTimeout(resolve, delay));
      continue;
    }

    throw new Error(`OpenAlex search failed: ${response.status} ${response.statusText}`);
  }

  throw new Error("OpenAlex search failed after retries");
}

export async function searchOpenAlex(
  query: string,
  maxResults: number = 20,
  sortBy: string = "cited_by_count:desc"
): Promise<OpenAlexArticle[]> {
  const params = new URLSearchParams({
    search: query,
    filter: "type:article",
    sort: sortBy,
    per_page: maxResults.toString(),
    mailto: POLITE_EMAIL,
  });

  const response = await fetchWithRetry(`${OPENALEX_BASE_URL}?${params}`);
  const data = (await response.json()) as OpenAlexResponse;
  const works = data.results || [];

  return works.map((work) => {
    // Extract PMID from ids
    let pmid: string | undefined;
    if (work.ids?.pmid) {
      // Format: "https://pubmed.ncbi.nlm.nih.gov/12345678"
      const pmidMatch = work.ids.pmid.match(/(\d+)$/);
      pmid = pmidMatch?.[1];
    }

    // Extract DOI
    let doi: string | undefined;
    if (work.doi) {
      doi = work.doi.replace("https://doi.org/", "");
    } else if (work.ids?.doi) {
      doi = work.ids.doi.replace("https://doi.org/", "");
    }

    // Extract authors
    const authors = (work.authorships || [])
      .map((a) => a.author?.display_name)
      .filter((name): name is string => !!name);

    return {
      openalexId: work.id?.replace("https://openalex.org/", "") || "",
      title: work.title || "Untitled",
      abstract: reconstructAbstract(work.abstract_inverted_index),
      authors,
      journal: work.primary_location?.source?.display_name || "Unknown",
      publicationDate: work.publication_date || "",
      publicationYear: work.publication_year?.toString() || "",
      doi,
      pmid,
      citationCount: work.cited_by_count || 0,
      url: work.id || "",
      evidenceLevel: inferEvidenceLevel(work.type, work.title),
    };
  });
}

export const openalexSearchTool = tool(
  async ({ query, maxResults, sortBy }) => {
    try {
      const articles = await searchOpenAlex(
        query,
        maxResults || 20,
        sortBy || "cited_by_count:desc"
      );

      return JSON.stringify({
        success: true,
        count: articles.length,
        source: "openalex",
        articles: articles.map((a) => ({
          openalexId: a.openalexId,
          title: a.title,
          abstract: a.abstract || null,
          authors: a.authors.join(", "),
          journal: a.journal,
          publicationDate: a.publicationDate,
          publicationYear: a.publicationYear,
          doi: a.doi,
          pmid: a.pmid,
          citationCount: a.citationCount,
          url: a.url,
          evidenceLevel: a.evidenceLevel,
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
    name: "openalex_search",
    description:
      "Searches OpenAlex database for scientific literature. No API key required. Provides citation counts and broad coverage. Good fallback when Scopus is unavailable.",
    schema: z.object({
      query: z.string().describe("Search query"),
      maxResults: z
        .number()
        .optional()
        .nullable()
        .default(20)
        .describe("Maximum number of results"),
      sortBy: z
        .string()
        .optional()
        .nullable()
        .default("cited_by_count:desc")
        .describe("Sort order: cited_by_count:desc (default), publication_date:desc, relevance_score:desc"),
    }),
  }
);
