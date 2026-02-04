import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { EVIDENCE_LEVELS } from "./mesh-mapping";

const NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";

export interface PubMedArticle {
  pmid: string;
  title: string;
  abstract: string;
  authors: string[];
  journal: string;
  publicationDate: string;
  publicationType: string[];
  meshTerms: string[];
  doi?: string;
  evidenceLevel?: string;
}

interface ESearchResult {
  esearchresult: {
    count: string;
    idlist: string[];
    querytranslation?: string;
  };
}

interface EFetchResult {
  PubmedArticleSet: {
    PubmedArticle?: Array<{
      MedlineCitation: {
        PMID: { _text: string };
        Article: {
          ArticleTitle: { _text: string } | string;
          Abstract?: {
            AbstractText: Array<{ _text: string }> | { _text: string } | string;
          };
          AuthorList?: {
            Author?: Array<{
              LastName?: { _text: string };
              ForeName?: { _text: string };
              CollectiveName?: { _text: string };
            }>;
          };
          Journal: {
            Title: { _text: string } | string;
          };
          PublicationTypeList?: {
            PublicationType: Array<{ _text: string }> | { _text: string };
          };
          ArticleDate?: Array<{
            Year: { _text: string };
            Month: { _text: string };
            Day: { _text: string };
          }>;
        };
        MeshHeadingList?: {
          MeshHeading?: Array<{
            DescriptorName: { _text: string };
          }>;
        };
      };
      PubmedData?: {
        ArticleIdList?: {
          ArticleId?: Array<{
            _attr?: { IdType: string };
            _text: string;
          }>;
        };
      };
    }>;
  };
}

async function searchPubMed(
  query: string,
  maxResults: number = 20,
  apiKey?: string
): Promise<string[]> {
  const params = new URLSearchParams({
    db: "pubmed",
    term: query,
    retmax: maxResults.toString(),
    retmode: "json",
    sort: "relevance",
  });

  if (apiKey) {
    params.append("api_key", apiKey);
  }

  const response = await fetch(`${NCBI_BASE_URL}/esearch.fcgi?${params}`);

  if (!response.ok) {
    throw new Error(`PubMed search failed: ${response.statusText}`);
  }

  const data = (await response.json()) as ESearchResult;
  return data.esearchresult.idlist;
}

async function fetchPubMedDetails(
  pmids: string[],
  apiKey?: string
): Promise<PubMedArticle[]> {
  if (pmids.length === 0) return [];

  const params = new URLSearchParams({
    db: "pubmed",
    id: pmids.join(","),
    retmode: "xml",
    rettype: "abstract",
  });

  if (apiKey) {
    params.append("api_key", apiKey);
  }

  const response = await fetch(`${NCBI_BASE_URL}/efetch.fcgi?${params}`);

  if (!response.ok) {
    throw new Error(`PubMed fetch failed: ${response.statusText}`);
  }

  const xmlText = await response.text();

  // Parse XML using a simple approach (or use xml2js in production)
  const articles: PubMedArticle[] = [];

  // Simple regex-based XML parsing for key fields
  const articleMatches = Array.from(xmlText.matchAll(/<PubmedArticle>([\s\S]*?)<\/PubmedArticle>/g));

  for (const match of articleMatches) {
    const articleXml = match[1];

    const pmid = articleXml.match(/<PMID[^>]*>(\d+)<\/PMID>/)?.[1] || "";
    const title = articleXml.match(/<ArticleTitle[^>]*>([\s\S]*?)<\/ArticleTitle>/)?.[1] || "";
    const abstractMatch = articleXml.match(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/g);
    const abstract = abstractMatch
      ? abstractMatch.map((a: string) => a.replace(/<[^>]+>/g, "")).join(" ")
      : "";

    const journal = articleXml.match(/<Title[^>]*>([\s\S]*?)<\/Title>/)?.[1] || "";

    // Extract authors
    const authors: string[] = [];
    const authorMatches = Array.from(articleXml.matchAll(
      /<Author[^>]*>[\s\S]*?<LastName>([^<]+)<\/LastName>[\s\S]*?<ForeName>([^<]+)<\/ForeName>[\s\S]*?<\/Author>/g
    ));
    for (const authorMatch of authorMatches) {
      authors.push(`${authorMatch[2]} ${authorMatch[1]}`);
    }

    // Extract publication types
    const pubTypes: string[] = [];
    const pubTypeMatches = Array.from(articleXml.matchAll(/<PublicationType[^>]*>([^<]+)<\/PublicationType>/g));
    for (const ptMatch of pubTypeMatches) {
      pubTypes.push(ptMatch[1]);
    }

    // Extract MeSH terms
    const meshTerms: string[] = [];
    const meshMatches = Array.from(articleXml.matchAll(/<DescriptorName[^>]*>([^<]+)<\/DescriptorName>/g));
    for (const meshMatch of meshMatches) {
      meshTerms.push(meshMatch[1]);
    }

    // Extract DOI
    const doi = articleXml.match(/<ArticleId IdType="doi">([^<]+)<\/ArticleId>/)?.[1];

    // Extract date
    const year = articleXml.match(/<Year>(\d{4})<\/Year>/)?.[1] || "";
    const month = articleXml.match(/<Month>(\d{1,2}|\w+)<\/Month>/)?.[1] || "";
    const day = articleXml.match(/<Day>(\d{1,2})<\/Day>/)?.[1] || "";
    const publicationDate = [year, month, day].filter(Boolean).join("-");

    // Determine evidence level
    let evidenceLevel = "Level V";
    const pubTypeStr = pubTypes.join(" ").toLowerCase();
    const abstractLower = abstract.toLowerCase();

    for (const [key, value] of Object.entries(EVIDENCE_LEVELS)) {
      if (pubTypeStr.includes(key) || abstractLower.includes(key)) {
        evidenceLevel = value.level;
        break;
      }
    }

    articles.push({
      pmid,
      title: title.replace(/<[^>]+>/g, ""), // Strip any remaining HTML
      abstract: abstract.replace(/<[^>]+>/g, ""),
      authors,
      journal: journal.replace(/<[^>]+>/g, ""),
      publicationDate,
      publicationType: pubTypes,
      meshTerms,
      doi,
      evidenceLevel,
    });
  }

  return articles;
}

export const pubmedSearchTool = tool(
  async ({ query, maxResults, apiKey }) => {
    try {
      const pmids = await searchPubMed(query, maxResults || 20, apiKey);
      const articles = await fetchPubMedDetails(pmids, apiKey);

      return JSON.stringify({
        success: true,
        count: articles.length,
        articles: articles.map((a) => ({
          pmid: a.pmid,
          title: a.title,
          abstract: a.abstract.substring(0, 500) + (a.abstract.length > 500 ? "..." : ""),
          authors: a.authors.slice(0, 5).join(", ") + (a.authors.length > 5 ? " et al." : ""),
          journal: a.journal,
          publicationDate: a.publicationDate,
          publicationType: a.publicationType.join(", "),
          evidenceLevel: a.evidenceLevel,
          doi: a.doi,
          url: `https://pubmed.ncbi.nlm.nih.gov/${a.pmid}/`,
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
    name: "pubmed_search",
    description:
      "Searches PubMed/MEDLINE for medical literature. Supports MeSH terms, Boolean operators (AND, OR, NOT), and field tags like [ti] for title, [ab] for abstract, [mh] for MeSH.",
    schema: z.object({
      query: z.string().describe("PubMed search query (supports MeSH terms and Boolean operators)"),
      maxResults: z.number().optional().default(20).describe("Maximum number of results (default: 20)"),
      apiKey: z.string().optional().describe("Optional NCBI API key for higher rate limits"),
    }),
  }
);

export { searchPubMed, fetchPubMedDetails };
