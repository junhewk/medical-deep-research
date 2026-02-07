import { z } from "zod";
import { tool } from "@langchain/core/tools";

const S2_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search";
const S2_FIELDS = "paperId,title,abstract,year,authors,venue,citationCount,externalIds,publicationTypes,journal";

/**
 * Infer evidence level from Semantic Scholar publicationTypes and title
 */
function inferEvidenceLevel(
  publicationTypes?: string[],
  title?: string
): string | undefined {
  const t = title?.toLowerCase() ?? "";
  const types = publicationTypes?.map((p) => p.toLowerCase()) || [];

  if (/systematic\s*review|meta[\s-]?analysis/.test(t)) return "Level I";
  if (types.includes("review")) return "Level I";

  if (/randomized|randomised|rct\b/.test(t)) return "Level II";

  if (/cohort|case[\s-]?control|prospective|retrospective/.test(t)) return "Level III";
  if (types.includes("casereport") || /case\s*(series|report)/.test(t)) return "Level IV";

  return undefined;
}

export interface SemanticScholarArticle {
  paperId: string;
  title: string;
  abstract?: string;
  authors: string[];
  journal: string;
  publicationYear: string;
  doi?: string;
  pmid?: string;
  citationCount: number;
  url: string;
  evidenceLevel?: string;
}

interface S2Paper {
  paperId?: string;
  title?: string;
  abstract?: string;
  year?: number;
  authors?: Array<{ name?: string }>;
  venue?: string;
  citationCount?: number;
  externalIds?: {
    PubMed?: string;
    DOI?: string;
    ArXiv?: string;
  };
  publicationTypes?: string[];
  journal?: {
    name?: string;
    volume?: string;
    pages?: string;
  };
}

interface S2Response {
  total?: number;
  data?: S2Paper[];
}

async function fetchWithRetry(
  url: string,
  apiKey?: string,
  maxRetries: number = 3
): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (apiKey) {
    headers["x-api-key"] = apiKey;
  }

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, { headers });

    if (response.ok) return response;

    if (response.status === 429 && attempt < maxRetries) {
      const delay = Math.pow(2, attempt) * 1000;
      console.log(`[SemanticScholar] Rate limited, retrying in ${delay}ms...`);
      await new Promise((resolve) => setTimeout(resolve, delay));
      continue;
    }

    throw new Error(`Semantic Scholar search failed: ${response.status} ${response.statusText}`);
  }

  throw new Error("Semantic Scholar search failed after retries");
}

export async function searchSemanticScholar(
  query: string,
  maxResults: number = 20,
  apiKey?: string
): Promise<SemanticScholarArticle[]> {
  const params = new URLSearchParams({
    query,
    limit: Math.min(maxResults, 100).toString(),
    fields: S2_FIELDS,
    fieldsOfStudy: "Medicine",
  });

  const response = await fetchWithRetry(
    `${S2_BASE_URL}?${params}`,
    apiKey
  );
  const data = (await response.json()) as S2Response;
  const papers = data.data || [];

  return papers.map((paper) => {
    const authors = (paper.authors || [])
      .map((a) => a.name)
      .filter((name): name is string => !!name);

    return {
      paperId: paper.paperId || "",
      title: paper.title || "Untitled",
      abstract: paper.abstract || undefined,
      authors,
      journal: paper.journal?.name || paper.venue || "Unknown",
      publicationYear: paper.year?.toString() || "",
      doi: paper.externalIds?.DOI,
      pmid: paper.externalIds?.PubMed,
      citationCount: paper.citationCount || 0,
      url: paper.paperId
        ? `https://www.semanticscholar.org/paper/${paper.paperId}`
        : "",
      evidenceLevel: inferEvidenceLevel(paper.publicationTypes, paper.title),
    };
  });
}

export const semanticScholarSearchTool = tool(
  async ({ query, maxResults, apiKey }) => {
    try {
      const articles = await searchSemanticScholar(
        query,
        maxResults || 20,
        apiKey || undefined
      );

      return JSON.stringify({
        success: true,
        count: articles.length,
        source: "semantic_scholar",
        articles: articles.map((a) => ({
          paperId: a.paperId,
          title: a.title,
          abstract: a.abstract || null,
          authors: a.authors.join(", "),
          journal: a.journal,
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
    name: "semantic_scholar_search",
    description:
      "Searches Semantic Scholar for scientific literature. No API key required (100 req/5min free tier). Filters by Medicine field of study. Good fallback when Scopus is unavailable.",
    schema: z.object({
      query: z.string().describe("Search query"),
      maxResults: z
        .number()
        .optional()
        .nullable()
        .default(20)
        .describe("Maximum number of results"),
      apiKey: z
        .string()
        .optional()
        .nullable()
        .describe("Optional Semantic Scholar API key for higher rate limits"),
    }),
  }
);
