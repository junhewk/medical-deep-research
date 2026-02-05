import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { db } from "@/db";
import { meshCache, meshLookupIndex } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";

/**
 * Dynamic MeSH term resolver using NLM's MeSH RDF REST API
 *
 * Features:
 * - Queries NLM API for term lookup
 * - Caches results in SQLite
 * - Returns related terms (broader, narrower, synonyms)
 * - Falls back to cached data if API unavailable
 *
 * API Reference: https://hhs.github.io/meshrdf/sparql-and-uri-requests
 */

export interface MeshLookupResult {
  descriptorUI: string; // e.g., "D009204"
  label: string; // Primary MeSH heading
  synonyms: string[]; // Entry terms
  broaderTerms: string[]; // Parent terms
  narrowerTerms: string[]; // Child terms
  treeNumbers: string[]; // Hierarchy codes
  scopeNote?: string; // Definition
}

interface NlmLookupResponse {
  resource: string;
  label: string;
}

interface NlmDescriptorJson {
  "@id": string;
  label?: { "@value": string };
  prefLabel?: { "@value": string };
  altLabel?: Array<{ "@value": string }> | { "@value": string };
  scopeNote?: { "@value": string };
  treeNumber?: Array<{ "@value": string }> | { "@value": string };
  broaderDescriptor?: Array<{ "@id": string }> | { "@id": string };
  narrowerDescriptor?: Array<{ "@id": string }> | { "@id": string };
}

// Cache freshness threshold (7 days)
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Check if cached data is still fresh
 */
function isCacheFresh(fetchedAt: Date | null): boolean {
  if (!fetchedAt) return false;
  return Date.now() - fetchedAt.getTime() < CACHE_TTL_MS;
}

/**
 * Extract UID from MeSH URI
 * e.g., "http://id.nlm.nih.gov/mesh/D009204" -> "D009204"
 */
function extractUid(uri: string): string {
  const parts = uri.split("/");
  return parts[parts.length - 1];
}

/**
 * Normalize array-or-single values from NLM JSON-LD
 */
function normalizeArray<T>(value: T | T[] | undefined): T[] {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

/**
 * Parse NLM descriptor JSON into our format
 */
function parseDescriptorJson(json: NlmDescriptorJson): MeshLookupResult {
  const descriptorUI = extractUid(json["@id"]);
  const label = json.prefLabel?.["@value"] || json.label?.["@value"] || "";

  // Extract alternate labels (synonyms)
  const altLabels = normalizeArray(json.altLabel);
  const synonyms = altLabels.map((al) => al["@value"]).filter(Boolean);

  // Extract tree numbers
  const treeNums = normalizeArray(json.treeNumber);
  const treeNumbers = treeNums.map((tn) => tn["@value"]).filter(Boolean);

  // Extract broader terms (parent descriptors)
  const broaderDescs = normalizeArray(json.broaderDescriptor);
  const broaderTerms = broaderDescs.map((bd) => extractUid(bd["@id"])).filter(Boolean);

  // Extract narrower terms (child descriptors)
  const narrowerDescs = normalizeArray(json.narrowerDescriptor);
  const narrowerTerms = narrowerDescs.map((nd) => extractUid(nd["@id"])).filter(Boolean);

  // Scope note (definition)
  const scopeNote = json.scopeNote?.["@value"];

  return {
    descriptorUI,
    label,
    synonyms,
    broaderTerms,
    narrowerTerms,
    treeNumbers,
    scopeNote,
  };
}

/**
 * Cache MeSH lookup results to database
 */
async function cacheResults(searchTerm: string, results: MeshLookupResult[]): Promise<void> {
  for (const result of results) {
    // Insert or update mesh_cache
    try {
      await db
        .insert(meshCache)
        .values({
          id: result.descriptorUI,
          label: result.label,
          alternateLabels: JSON.stringify(result.synonyms),
          treeNumbers: JSON.stringify(result.treeNumbers),
          broaderTerms: JSON.stringify(result.broaderTerms),
          narrowerTerms: JSON.stringify(result.narrowerTerms),
          scopeNote: result.scopeNote || null,
          fetchedAt: new Date(),
        })
        .onConflictDoUpdate({
          target: meshCache.id,
          set: {
            label: result.label,
            alternateLabels: JSON.stringify(result.synonyms),
            treeNumbers: JSON.stringify(result.treeNumbers),
            broaderTerms: JSON.stringify(result.broaderTerms),
            narrowerTerms: JSON.stringify(result.narrowerTerms),
            scopeNote: result.scopeNote || null,
            fetchedAt: new Date(),
          },
        });
    } catch (error) {
      console.error(`Failed to cache MeSH term ${result.descriptorUI}:`, error);
    }

    // Insert lookup index entry
    try {
      const indexId = generateId();
      await db
        .insert(meshLookupIndex)
        .values({
          id: indexId,
          searchTerm: searchTerm.toLowerCase(),
          meshId: result.descriptorUI,
          matchType: result.label.toLowerCase() === searchTerm.toLowerCase() ? "exact" : "contains",
        })
        .onConflictDoNothing();
    } catch (error) {
      // Index entry may already exist, ignore
    }
  }
}

/**
 * Format cached results into MeshLookupResult
 */
function formatCachedResult(cached: typeof meshCache.$inferSelect): MeshLookupResult {
  return {
    descriptorUI: cached.id,
    label: cached.label,
    synonyms: cached.alternateLabels ? JSON.parse(cached.alternateLabels) : [],
    broaderTerms: cached.broaderTerms ? JSON.parse(cached.broaderTerms) : [],
    narrowerTerms: cached.narrowerTerms ? JSON.parse(cached.narrowerTerms) : [],
    treeNumbers: cached.treeNumbers ? JSON.parse(cached.treeNumbers) : [],
    scopeNote: cached.scopeNote || undefined,
  };
}

/**
 * Clean and normalize a term for MeSH lookup
 * - Remove special characters that cause API issues
 * - Truncate overly long terms
 * - Extract key medical concepts from verbose descriptions
 */
function cleanTermForLookup(term: string): string | null {
  // Remove parenthetical content (often explanatory text)
  let cleaned = term.replace(/\([^)]*\)/g, "").trim();

  // Remove common punctuation that causes issues
  cleaned = cleaned.replace(/[,:;\/]/g, " ").replace(/\s+/g, " ").trim();

  // If term is too long (>100 chars), it's likely a description, not a concept
  if (cleaned.length > 100) {
    // Try to extract the first meaningful phrase
    const parts = cleaned.split(/\s+and\s+|\s+or\s+|\s+vs\.?\s+/i);
    if (parts[0] && parts[0].length > 3 && parts[0].length <= 100) {
      cleaned = parts[0].trim();
    } else {
      // Take first 50 chars and find word boundary
      cleaned = cleaned.substring(0, 50).replace(/\s+\S*$/, "").trim();
    }
  }

  // Skip very short terms or common words
  if (cleaned.length < 3 || /^(the|and|for|with|from|that|this)$/i.test(cleaned)) {
    return null;
  }

  return cleaned;
}

/**
 * Look up a single MeSH term using NLM API with caching
 */
export async function lookupMeshTerm(term: string): Promise<MeshLookupResult[]> {
  // Clean the term first
  const cleanedTerm = cleanTermForLookup(term);
  if (!cleanedTerm) {
    return [];
  }

  const normalizedTerm = cleanedTerm.toLowerCase().trim();

  // 1. Check cache first
  try {
    const cachedIndex = await db
      .select()
      .from(meshLookupIndex)
      .where(eq(meshLookupIndex.searchTerm, normalizedTerm))
      .limit(10);

    if (cachedIndex.length > 0) {
      const cachedResults: MeshLookupResult[] = [];
      for (const idx of cachedIndex) {
        if (idx.meshId) {
          const cached = await db
            .select()
            .from(meshCache)
            .where(eq(meshCache.id, idx.meshId))
            .limit(1);

          if (cached.length > 0 && isCacheFresh(cached[0].fetchedAt)) {
            cachedResults.push(formatCachedResult(cached[0]));
          }
        }
      }
      if (cachedResults.length > 0) {
        return cachedResults;
      }
    }
  } catch (error) {
    console.warn("Cache lookup failed, proceeding to API:", error);
  }

  // 2. Query NLM MeSH RDF API
  try {
    const apiUrl = `https://id.nlm.nih.gov/mesh/lookup?label=${encodeURIComponent(cleanedTerm)}&match=contains&limit=10`;
    const response = await fetch(apiUrl, {
      headers: {
        "Accept": "application/json",
        "User-Agent": "MedicalDeepResearch/2.0",
      },
      signal: AbortSignal.timeout(10000), // 10 second timeout
    });

    if (!response.ok) {
      console.warn(`NLM API returned ${response.status} for term: "${cleanedTerm}" (original: "${term.substring(0, 50)}...")`);
      return [];
    }

    const results: NlmLookupResponse[] = await response.json();

    if (!results || results.length === 0) {
      return [];
    }

    // 3. Fetch full descriptor details for each match
    const detailed: MeshLookupResult[] = [];

    for (const r of results.slice(0, 5)) {
      // Limit to 5 for performance
      try {
        const uid = extractUid(r.resource);
        const detailUrl = `https://id.nlm.nih.gov/mesh/${uid}.json`;
        const detailResponse = await fetch(detailUrl, {
          headers: { Accept: "application/json" },
          signal: AbortSignal.timeout(5000),
        });

        if (detailResponse.ok) {
          const detail: NlmDescriptorJson = await detailResponse.json();
          detailed.push(parseDescriptorJson(detail));
        }
      } catch (detailError) {
        // If detail fetch fails, use basic info from lookup
        detailed.push({
          descriptorUI: extractUid(r.resource),
          label: r.label,
          synonyms: [],
          broaderTerms: [],
          narrowerTerms: [],
          treeNumbers: [],
        });
      }
    }

    // 4. Cache results
    if (detailed.length > 0) {
      await cacheResults(term, detailed);
    }

    return detailed;
  } catch (error) {
    console.error(`NLM API lookup failed for term "${term}":`, error);

    // 5. Fallback to stale cache if available
    try {
      const staleIndex = await db
        .select()
        .from(meshLookupIndex)
        .where(eq(meshLookupIndex.searchTerm, normalizedTerm))
        .limit(10);

      const staleResults: MeshLookupResult[] = [];
      for (const idx of staleIndex) {
        if (idx.meshId) {
          const cached = await db.select().from(meshCache).where(eq(meshCache.id, idx.meshId)).limit(1);

          if (cached.length > 0) {
            staleResults.push(formatCachedResult(cached[0]));
          }
        }
      }
      return staleResults;
    } catch {
      return [];
    }
  }
}

/**
 * Look up multiple MeSH terms in batch
 */
export async function batchLookupMeshTerms(
  terms: string[]
): Promise<Record<string, MeshLookupResult[]>> {
  const results: Record<string, MeshLookupResult[]> = {};

  // Process in parallel with concurrency limit
  const concurrencyLimit = 3;
  for (let i = 0; i < terms.length; i += concurrencyLimit) {
    const batch = terms.slice(i, i + concurrencyLimit);
    const batchResults = await Promise.all(batch.map((term) => lookupMeshTerm(term)));

    batch.forEach((term, idx) => {
      results[term] = batchResults[idx];
    });
  }

  return results;
}

/**
 * Get unique MeSH labels from lookup results
 */
export function extractMeshLabels(results: Record<string, MeshLookupResult[]>): string[] {
  const labels = new Set<string>();

  for (const termResults of Object.values(results)) {
    for (const result of termResults) {
      labels.add(result.label);
      // Optionally include synonyms
      result.synonyms.slice(0, 2).forEach((syn) => labels.add(syn));
    }
  }

  return Array.from(labels);
}

/**
 * LangChain tool wrapper for mesh resolver
 */
export const meshResolverTool = tool(
  async ({ terms }) => {
    const results = await batchLookupMeshTerms(terms);

    return JSON.stringify({
      success: true,
      results,
      // Formatted for easy use in query building
      meshTerms: extractMeshLabels(results),
      // Summary of what was found
      summary: Object.entries(results)
        .map(([term, matches]) => {
          if (matches.length === 0) {
            return `"${term}": No MeSH match found`;
          }
          return `"${term}": ${matches.map((m) => m.label).join(", ")}`;
        })
        .join("\n"),
    });
  },
  {
    name: "mesh_resolver",
    description:
      "Resolves medical terms to official MeSH headings using NLM's MeSH RDF API. Returns exact matches, synonyms, and related terms for optimal PubMed query construction. Use this to find proper MeSH terms for specialized concepts not in the standard mapping.",
    schema: z.object({
      terms: z.array(z.string()).describe("Medical terms to resolve to MeSH headings"),
    }),
  }
);


/**
 * Extract key phrases from text for MeSH lookup.
 * Handles multi-word medical concepts better than simple word splitting.
 * Shared utility used by pico-query.ts and pcc-query.ts.
 */
export function extractKeyPhrases(text: string): string[] {
  const phrases: string[] = [];

  // Add the full text as a phrase
  const cleaned = text.trim();
  if (cleaned) {
    phrases.push(cleaned);
  }

  // Split on common delimiters and logical operators
  const parts = text.split(/[,;\/]|\band\b|\bor\b|\bvs\.?\b|\bversus\b/i);
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed && trimmed.length > 3 && !phrases.includes(trimmed)) {
      phrases.push(trimmed);
    }
  }

  // Extract potential medical terms (capitalized phrases, abbreviations)
  const medicalTerms = text.match(/\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b/g);
  if (medicalTerms) {
    for (const term of medicalTerms) {
      if (!phrases.includes(term)) {
        phrases.push(term);
      }
    }
  }

  return phrases.slice(0, 10); // Limit to prevent too many API calls
}
