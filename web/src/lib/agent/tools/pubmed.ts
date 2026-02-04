import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { EVIDENCE_LEVELS } from "./mesh-mapping";

const NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";

/**
 * Landmark medical journals - papers from these sources get scoring bonus
 */
const LANDMARK_JOURNALS = [
  "New England Journal of Medicine",
  "NEJM",
  "N Engl J Med",
  "Lancet",
  "The Lancet",
  "JAMA",
  "Journal of the American Medical Association",
  "BMJ",
  "British Medical Journal",
  "Circulation",
  "European Heart Journal",
  "Eur Heart J",
  "JACC",
  "Journal of the American College of Cardiology",
  "Annals of Internal Medicine",
  "Ann Intern Med",
  "Nature Medicine",
  "Nat Med",
  "Cell",
  "Science",
];

/**
 * Check if a journal is a landmark journal
 */
export function isLandmarkJournal(journal: string): boolean {
  if (!journal) return false;
  const journalLower = journal.toLowerCase();
  return LANDMARK_JOURNALS.some((lj) => journalLower.includes(lj.toLowerCase()));
}

/**
 * Search strategy types
 */
export type SearchStrategy = "standard" | "comprehensive";

/**
 * Date range for search filtering
 */
export interface DateRange {
  start?: string; // YYYY/MM/DD or YYYY
  end?: string;   // YYYY/MM/DD or YYYY
}

export interface PubMedArticle {
  pmid: string;
  title: string;
  abstract: string;
  /** Extracted conclusion section from structured abstract */
  conclusion?: string;
  /** Extracted results section from structured abstract */
  results?: string;
  authors: string[];
  journal: string;
  publicationDate: string;
  publicationType: string[];
  meshTerms: string[];
  doi?: string;
  evidenceLevel?: string;
  isLandmarkJournal?: boolean;
}

/**
 * Parse structured abstract sections from PubMed XML
 * PubMed returns structured abstracts with labeled sections like:
 * <AbstractText Label="CONCLUSIONS">...</AbstractText>
 */
function parseStructuredAbstract(abstractXml: string): {
  background?: string;
  methods?: string;
  results?: string;
  conclusion?: string;
  fullText: string;
} {
  const sections: Record<string, string> = {};
  let fullText = "";

  // Try to extract labeled sections
  const labeledMatches = Array.from(
    abstractXml.matchAll(/<AbstractText[^>]*Label="([^"]+)"[^>]*>([\s\S]*?)<\/AbstractText>/gi)
  );

  if (labeledMatches.length > 0) {
    // Structured abstract with labeled sections
    for (const match of labeledMatches) {
      const label = match[1].toLowerCase();
      const text = match[2].replace(/<[^>]+>/g, "").trim();
      sections[label] = text;
      fullText += text + " ";
    }
  } else {
    // Unstructured abstract - extract all AbstractText content
    const unstructuredMatches = Array.from(
      abstractXml.matchAll(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/gi)
    );
    fullText = unstructuredMatches.map((m) => m[1].replace(/<[^>]+>/g, "").trim()).join(" ");
  }

  // Map common variations of section labels to canonical names
  function findSection(...keys: string[]): string | undefined {
    for (const key of keys) {
      if (sections[key]) return sections[key];
    }
    return undefined;
  }

  const conclusion = findSection("conclusions", "conclusion", "interpretation", "findings");
  const results = findSection("results", "findings", "main results");
  const background = findSection("background", "context", "introduction", "objective", "objectives");
  const methods = findSection("methods", "method", "design", "setting");

  return {
    background,
    methods,
    results,
    conclusion,
    fullText: fullText.trim(),
  };
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
  apiKey?: string,
  options?: {
    sort?: "relevance" | "pub_date";
    dateRange?: DateRange;
  }
): Promise<string[]> {
  const params = new URLSearchParams({
    db: "pubmed",
    term: query,
    retmax: maxResults.toString(),
    retmode: "json",
    sort: options?.sort || "relevance",
  });

  // Add date range filtering
  if (options?.dateRange) {
    if (options.dateRange.start) {
      params.append("mindate", options.dateRange.start);
    }
    if (options.dateRange.end) {
      params.append("maxdate", options.dateRange.end);
    }
    params.append("datetype", "pdat"); // Publication date
  }

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

    // Extract Abstract section and parse structured abstract
    const abstractSection = articleXml.match(/<Abstract>([\s\S]*?)<\/Abstract>/)?.[1] || "";
    const parsedAbstract = parseStructuredAbstract(abstractSection);

    const journal = articleXml.match(/<Title[^>]*>([\s\S]*?)<\/Title>/)?.[1] || "";

    // Extract authors
    const authorMatches = Array.from(articleXml.matchAll(
      /<Author[^>]*>[\s\S]*?<LastName>([^<]+)<\/LastName>[\s\S]*?<ForeName>([^<]+)<\/ForeName>[\s\S]*?<\/Author>/g
    ));
    const authors = authorMatches.map((match) => `${match[2]} ${match[1]}`);

    // Extract publication types
    const pubTypeMatches = Array.from(articleXml.matchAll(/<PublicationType[^>]*>([^<]+)<\/PublicationType>/g));
    const pubTypes = pubTypeMatches.map((match) => match[1]);

    // Extract MeSH terms
    const meshMatches = Array.from(articleXml.matchAll(/<DescriptorName[^>]*>([^<]+)<\/DescriptorName>/g));
    const meshTerms = meshMatches.map((match) => match[1]);

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
    const abstractLower = parsedAbstract.fullText.toLowerCase();

    for (const [key, value] of Object.entries(EVIDENCE_LEVELS)) {
      if (pubTypeStr.includes(key) || abstractLower.includes(key)) {
        evidenceLevel = value.level;
        break;
      }
    }

    const cleanJournal = journal.replace(/<[^>]+>/g, "");
    articles.push({
      pmid,
      title: title.replace(/<[^>]+>/g, ""), // Strip any remaining HTML
      abstract: parsedAbstract.fullText, // FULL abstract, not truncated
      conclusion: parsedAbstract.conclusion, // Extracted conclusion section
      results: parsedAbstract.results, // Extracted results section
      authors,
      journal: cleanJournal,
      publicationDate,
      publicationType: pubTypes,
      meshTerms,
      doi,
      evidenceLevel,
      isLandmarkJournal: isLandmarkJournal(cleanJournal),
    });
  }

  return articles;
}

/**
 * Comprehensive multi-phase search strategy for clinical questions
 *
 * Phase 1: Recent RCTs (40% of results) - last 3 years, sorted by date
 * Phase 2: Recent systematic reviews (20% of results) - last 5 years
 * Phase 3: Relevance-based (40% of results) - no date filter, standard relevance
 *
 * This addresses the recency failure problem where older high-relevance papers
 * overshadow recent landmark trials (e.g., REDUCE-AMI 2024)
 */
async function comprehensivePubMedSearch(
  query: string,
  maxResults: number = 30,
  apiKey?: string
): Promise<PubMedArticle[]> {
  const currentYear = new Date().getFullYear();
  const allPmids = new Set<string>();

  // Calculate allocation
  const recentRctCount = Math.floor(maxResults * 0.4);
  const systematicReviewCount = Math.floor(maxResults * 0.2);
  const relevanceCount = maxResults - recentRctCount - systematicReviewCount;

  // Phase 1: Recent RCTs (last 3 years)
  const rctQuery = `${query} AND (randomized controlled trial[pt] OR clinical trial[pt])`;
  try {
    const rctPmids = await searchPubMed(rctQuery, recentRctCount, apiKey, {
      sort: "pub_date",
      dateRange: {
        start: `${currentYear - 3}/01/01`,
        end: `${currentYear}/12/31`,
      },
    });
    rctPmids.forEach((pmid) => allPmids.add(pmid));
  } catch (error) {
    console.warn("Phase 1 (RCT) search failed:", error);
  }

  // Phase 2: Recent systematic reviews (last 5 years)
  const srQuery = `${query} AND (systematic review[pt] OR meta-analysis[pt])`;
  try {
    const srPmids = await searchPubMed(srQuery, systematicReviewCount, apiKey, {
      sort: "pub_date",
      dateRange: {
        start: `${currentYear - 5}/01/01`,
        end: `${currentYear}/12/31`,
      },
    });
    srPmids.forEach((pmid) => allPmids.add(pmid));
  } catch (error) {
    console.warn("Phase 2 (SR) search failed:", error);
  }

  // Phase 3: Relevance-based (standard search, no date filter)
  try {
    const relevancePmids = await searchPubMed(query, relevanceCount, apiKey, {
      sort: "relevance",
    });
    relevancePmids.forEach((pmid) => allPmids.add(pmid));
  } catch (error) {
    console.warn("Phase 3 (relevance) search failed:", error);
  }

  // Fetch details for all unique PMIDs
  const uniquePmids = Array.from(allPmids);
  if (uniquePmids.length === 0) {
    return [];
  }

  const articles = await fetchPubMedDetails(uniquePmids, apiKey);

  // Sort: prioritize recent landmark journal articles, then by recency
  articles.sort((a, b) => {
    // Landmark journal bonus
    const aLandmark = a.isLandmarkJournal ? 1 : 0;
    const bLandmark = b.isLandmarkJournal ? 1 : 0;
    if (aLandmark !== bLandmark) return bLandmark - aLandmark;

    // Then by date (more recent first)
    const aDate = new Date(a.publicationDate || "1900").getTime();
    const bDate = new Date(b.publicationDate || "1900").getTime();
    return bDate - aDate;
  });

  return articles;
}

export const pubmedSearchTool = tool(
  async ({ query, maxResults, apiKey, searchStrategy, dateRange }) => {
    try {
      let articles: PubMedArticle[];

      if (searchStrategy === "comprehensive") {
        // Use multi-phase comprehensive search for clinical questions
        articles = await comprehensivePubMedSearch(query, maxResults || 30, apiKey);
      } else {
        // Standard single-phase search
        const pmids = await searchPubMed(query, maxResults || 20, apiKey, {
          sort: "relevance",
          dateRange: dateRange ? {
            start: dateRange.start,
            end: dateRange.end,
          } : undefined,
        });
        articles = await fetchPubMedDetails(pmids, apiKey);
      }

      return JSON.stringify({
        success: true,
        count: articles.length,
        searchStrategy: searchStrategy || "standard",
        articles: articles.map((a) => ({
          pmid: a.pmid,
          title: a.title,
          // CRITICAL: Return FULL abstract to prevent hallucination from incomplete data
          abstract: a.abstract,
          // Extracted conclusion section - most important for accurate claims
          conclusion: a.conclusion || null,
          // Extracted results section
          results: a.results || null,
          authors: a.authors.slice(0, 5).join(", ") + (a.authors.length > 5 ? " et al." : ""),
          journal: a.journal,
          publicationDate: a.publicationDate,
          publicationType: a.publicationType.join(", "),
          evidenceLevel: a.evidenceLevel,
          isLandmarkJournal: a.isLandmarkJournal,
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
      "Searches PubMed/MEDLINE for medical literature. Supports MeSH terms, Boolean operators (AND, OR, NOT), and field tags like [ti] for title, [ab] for abstract, [mh] for MeSH. Use 'comprehensive' strategy for clinical questions to prioritize recent RCTs and landmark trials.",
    schema: z.object({
      query: z.string().describe("PubMed search query (supports MeSH terms and Boolean operators)"),
      maxResults: z.number().optional().default(20).describe("Maximum number of results (default: 20, use 30 for comprehensive)"),
      apiKey: z.string().optional().describe("Optional NCBI API key for higher rate limits"),
      searchStrategy: z.enum(["standard", "comprehensive"]).optional().default("standard").describe("Search strategy: 'standard' for relevance-based, 'comprehensive' for multi-phase clinical search prioritizing recent RCTs"),
      dateRange: z.object({
        start: z.string().optional().describe("Start date (YYYY/MM/DD or YYYY)"),
        end: z.string().optional().describe("End date (YYYY/MM/DD or YYYY)"),
      }).optional().describe("Optional date range filter (only for standard strategy)"),
    }),
  }
);

export { searchPubMed, fetchPubMedDetails, comprehensivePubMedSearch };
