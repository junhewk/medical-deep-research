import { z } from "zod";
import { tool } from "@langchain/core/tools";

const SCOPUS_BASE_URL = "https://api.elsevier.com/content/search/scopus";

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

async function searchScopus(
  query: string,
  maxResults: number = 20,
  apiKey: string
): Promise<ScopusArticle[]> {
  const params = new URLSearchParams({
    query: query,
    count: maxResults.toString(),
    sort: "relevancy",
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
  async ({ query, maxResults, apiKey }) => {
    if (!apiKey) {
      return JSON.stringify({
        success: false,
        error: "Scopus API key is required. Please configure it in Settings > API Keys.",
      });
    }

    try {
      const articles = await searchScopus(query, maxResults || 20, apiKey);

      return JSON.stringify({
        success: true,
        count: articles.length,
        articles: articles.map((a) => ({
          scopusId: a.scopusId,
          title: a.title,
          abstract: a.abstract
            ? a.abstract.substring(0, 500) + (a.abstract.length > 500 ? "..." : "")
            : null,
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
      "Searches Scopus database for scientific literature. Requires Scopus API key (BYOK). Supports complex queries with AND, OR, NOT operators.",
    schema: z.object({
      query: z.string().describe("Scopus search query"),
      maxResults: z.number().optional().default(20).describe("Maximum number of results"),
      apiKey: z.string().describe("Scopus/Elsevier API key"),
    }),
  }
);

export { searchScopus };
