import { z } from "zod";
import { tool } from "@langchain/core/tools";

const COCHRANE_BASE_URL = "https://www.cochranelibrary.com/api";

export interface CochraneReview {
  id: string;
  title: string;
  abstract?: string;
  authors: string[];
  publicationDate: string;
  doi?: string;
  reviewType: string; // Intervention, Diagnostic, etc.
  url: string;
  lastUpdated?: string;
}

interface CochraneSearchResponse {
  results: {
    total: number;
    items: Array<{
      id: string;
      title: string;
      abstract?: string;
      authors?: Array<{ name: string }>;
      publicationDate?: string;
      doi?: string;
      reviewType?: string;
    }>;
  };
}

async function searchCochrane(
  query: string,
  maxResults: number = 20,
  apiKey?: string
): Promise<CochraneReview[]> {
  // Note: Cochrane API access may require institutional subscription
  // This is a simplified implementation
  const params = new URLSearchParams({
    q: query,
    limit: maxResults.toString(),
    type: "reviews", // Focus on systematic reviews
  });

  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }

  try {
    const response = await fetch(`${COCHRANE_BASE_URL}/search?${params}`, {
      headers,
    });

    if (!response.ok) {
      // Fall back to alternative approach using Cochrane website
      return await searchCochraneAlternative(query, maxResults);
    }

    const data = (await response.json()) as CochraneSearchResponse;

    return data.results.items.map((item) => ({
      id: item.id,
      title: item.title,
      abstract: item.abstract,
      authors: item.authors?.map((a) => a.name) || [],
      publicationDate: item.publicationDate || "",
      doi: item.doi,
      reviewType: item.reviewType || "Systematic Review",
      url: `https://www.cochranelibrary.com/cdsr/doi/${item.doi}/full`,
    }));
  } catch {
    // Fall back to PubMed search for Cochrane reviews
    return await searchCochraneAlternative(query, maxResults);
  }
}

async function searchCochraneAlternative(
  query: string,
  maxResults: number
): Promise<CochraneReview[]> {
  // Use PubMed to search for Cochrane reviews as fallback
  const pubmedQuery = `${query} AND ("Cochrane Database Syst Rev"[Journal])`;

  const params = new URLSearchParams({
    db: "pubmed",
    term: pubmedQuery,
    retmax: maxResults.toString(),
    retmode: "json",
  });

  const searchResponse = await fetch(
    `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?${params}`
  );

  if (!searchResponse.ok) {
    return [];
  }

  const searchData = await searchResponse.json();
  const pmids = searchData.esearchresult?.idlist || [];

  if (pmids.length === 0) return [];

  // Fetch details
  const fetchParams = new URLSearchParams({
    db: "pubmed",
    id: pmids.join(","),
    retmode: "xml",
  });

  const fetchResponse = await fetch(
    `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?${fetchParams}`
  );

  if (!fetchResponse.ok) return [];

  const xmlText = await fetchResponse.text();
  const reviews: CochraneReview[] = [];

  const articleMatches = Array.from(xmlText.matchAll(/<PubmedArticle>([\s\S]*?)<\/PubmedArticle>/g));

  for (const match of articleMatches) {
    const articleXml = match[1];

    const pmid = articleXml.match(/<PMID[^>]*>(\d+)<\/PMID>/)?.[1] || "";
    const title = articleXml.match(/<ArticleTitle[^>]*>([\s\S]*?)<\/ArticleTitle>/)?.[1] || "";
    const abstractMatch = articleXml.match(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/g);
    const abstract = abstractMatch
      ? abstractMatch.map((a: string) => a.replace(/<[^>]+>/g, "")).join(" ")
      : undefined;

    const authors: string[] = [];
    const authorMatches = Array.from(articleXml.matchAll(
      /<Author[^>]*>[\s\S]*?<LastName>([^<]+)<\/LastName>[\s\S]*?<ForeName>([^<]+)<\/ForeName>[\s\S]*?<\/Author>/g
    ));
    for (const authorMatch of authorMatches) {
      authors.push(`${authorMatch[2]} ${authorMatch[1]}`);
    }

    const year = articleXml.match(/<Year>(\d{4})<\/Year>/)?.[1] || "";
    const doi = articleXml.match(/<ArticleId IdType="doi">([^<]+)<\/ArticleId>/)?.[1];

    reviews.push({
      id: pmid,
      title: title.replace(/<[^>]+>/g, ""),
      abstract: abstract?.replace(/<[^>]+>/g, ""),
      authors,
      publicationDate: year,
      doi,
      reviewType: "Cochrane Systematic Review",
      url: doi
        ? `https://www.cochranelibrary.com/cdsr/doi/${doi}/full`
        : `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`,
    });
  }

  return reviews;
}

export const cochraneSearchTool = tool(
  async ({ query, maxResults, apiKey }) => {
    try {
      const reviews = await searchCochrane(query, maxResults || 20, apiKey ?? undefined);

      return JSON.stringify({
        success: true,
        count: reviews.length,
        note: "Results are Cochrane Systematic Reviews (Level I evidence)",
        reviews: reviews.map((r) => ({
          id: r.id,
          title: r.title,
          // CRITICAL: Return FULL abstract to prevent hallucination from incomplete data
          abstract: r.abstract || null,
          authors: r.authors.slice(0, 5).join(", ") + (r.authors.length > 5 ? " et al." : ""),
          publicationDate: r.publicationDate,
          doi: r.doi,
          reviewType: r.reviewType,
          evidenceLevel: "Level I",
          url: r.url,
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
    name: "cochrane_search",
    description:
      "Searches the Cochrane Library for systematic reviews and meta-analyses. Returns Level I evidence. Falls back to PubMed search for Cochrane reviews if direct API is unavailable.",
    schema: z.object({
      query: z.string().describe("Search query for Cochrane reviews"),
      maxResults: z.number().optional().nullable().default(10).describe("Maximum number of results"),
      apiKey: z.string().optional().nullable().describe("Optional Cochrane API key"),
    }),
  }
);

export { searchCochrane };
