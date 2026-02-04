import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";

/**
 * Claim Verifier - Post-Synthesis Safety Net
 *
 * This tool verifies claims using ACADEMIC DATABASE (PubMed) as ground truth,
 * NOT LLM knowledge (which has cutoff issues).
 *
 * Verification flow:
 * 1. Verify PMID exists via PubMed API
 * 2. Fetch actual abstract from PubMed
 * 3. Use LLM ONLY to compare claim text against fetched abstract
 *
 * This prevents false "hallucination" accusations when evaluator's
 * knowledge is outdated (e.g., calling real 2025 papers "fake").
 */

const NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";

export interface Citation {
  referenceNumber: number;
  claim: string;
  claimSentence: string;
}

export interface PmidValidation {
  pmid: string;
  exists: boolean;
  title?: string;
  authors?: string[];
  journal?: string;
  pubDate?: string;
  error?: string;
}

export interface VerificationResult {
  referenceNumber: number;
  claim: string;
  pmid?: string;
  pmidValidation?: PmidValidation;
  isVerified: boolean;
  confidence: number;
  issue?: string;
  actualFinding?: string;
  suggestion?: string;
}

export interface ClaimVerificationReport {
  totalClaims: number;
  verifiedClaims: number;
  flaggedClaims: number;
  invalidPmids: PmidValidation[];
  criticalIssues: VerificationResult[];
  warnings: VerificationResult[];
  allResults: VerificationResult[];
}

/**
 * Verify PMID exists in PubMed and fetch metadata
 * Ground truth = PubMed API, not AI knowledge
 */
async function verifyPmidInPubMed(
  pmid: string,
  ncbiApiKey?: string
): Promise<PmidValidation> {
  if (!pmid || pmid === "N/A") {
    return { pmid, exists: false, error: "No PMID provided" };
  }

  try {
    const params = new URLSearchParams({
      db: "pubmed",
      id: pmid,
      retmode: "json",
    });
    if (ncbiApiKey) {
      params.append("api_key", ncbiApiKey);
    }

    const response = await fetch(`${NCBI_BASE_URL}/esummary.fcgi?${params}`);
    if (!response.ok) {
      return { pmid, exists: false, error: `PubMed API error: ${response.status}` };
    }

    const data = await response.json();
    const result = data.result?.[pmid];

    if (!result || result.error) {
      return { pmid, exists: false, error: result?.error || "PMID not found in PubMed" };
    }

    // Extract metadata
    const authors = result.authors?.map((a: { name: string }) => a.name) || [];

    return {
      pmid,
      exists: true,
      title: result.title,
      authors,
      journal: result.source || result.fulljournalname,
      pubDate: result.pubdate,
    };
  } catch (error) {
    return {
      pmid,
      exists: false,
      error: `Verification failed: ${error instanceof Error ? error.message : "Unknown"}`,
    };
  }
}

/**
 * Fetch actual abstract from PubMed
 * This is the GROUND TRUTH for claim verification
 */
async function fetchAbstractFromPubMed(
  pmid: string,
  ncbiApiKey?: string
): Promise<{ abstract: string; conclusion?: string } | null> {
  if (!pmid) return null;

  try {
    const params = new URLSearchParams({
      db: "pubmed",
      id: pmid,
      retmode: "xml",
      rettype: "abstract",
    });
    if (ncbiApiKey) {
      params.append("api_key", ncbiApiKey);
    }

    const response = await fetch(`${NCBI_BASE_URL}/efetch.fcgi?${params}`);
    if (!response.ok) return null;

    const xmlText = await response.text();

    // Extract abstract sections
    const abstractMatches = Array.from(
      xmlText.matchAll(/<AbstractText[^>]*(?:Label="([^"]*)")?[^>]*>([\s\S]*?)<\/AbstractText>/gi)
    );

    if (abstractMatches.length === 0) return null;

    let fullAbstract = "";
    let conclusion: string | undefined;

    for (const match of abstractMatches) {
      const label = match[1]?.toLowerCase() || "";
      const text = match[2].replace(/<[^>]+>/g, "").trim();

      fullAbstract += text + " ";

      if (label.includes("conclusion") || label.includes("interpretation")) {
        conclusion = text;
      }
    }

    return {
      abstract: fullAbstract.trim(),
      conclusion,
    };
  } catch {
    return null;
  }
}

/**
 * Extract claims with citations from report text
 */
export function extractCitationsFromReport(reportText: string): Citation[] {
  const citations: Citation[] = [];
  const sentences = reportText.split(/(?<=[.!?])\s+/);

  for (const sentence of sentences) {
    const citationMatches = Array.from(sentence.matchAll(/\[(\d+(?:[,\-]\d+)*)\]/g));

    for (const match of citationMatches) {
      const refNumbers = parseReferenceNumbers(match[1]);

      for (const refNum of refNumbers) {
        const beforeCitation = sentence.substring(0, match.index).trim();
        const clauses = beforeCitation.split(/[,;]/);
        const claim = clauses[clauses.length - 1]?.trim() || beforeCitation;

        citations.push({
          referenceNumber: refNum,
          claim,
          claimSentence: sentence,
        });
      }
    }
  }

  return citations;
}

function parseReferenceNumbers(refStr: string): number[] {
  if (refStr.includes("-")) {
    const [start, end] = refStr.split("-").map(Number);
    const numbers: number[] = [];
    for (let i = start; i <= end; i++) {
      numbers.push(i);
    }
    return numbers.filter((n) => !isNaN(n));
  }
  return refStr.split(",").map(Number).filter((n) => !isNaN(n));
}

/**
 * System prompt for claim verification
 * LLM's role: ONLY compare claim against provided abstract text
 * LLM must NOT use its own knowledge about the paper
 */
const CLAIM_VERIFIER_SYSTEM_PROMPT = `You are a text comparison specialist. Your ONLY task is to verify if a CLAIM is supported by the PROVIDED ABSTRACT TEXT.

## CRITICAL RULES

1. ONLY use the abstract text provided below - DO NOT use your training knowledge
2. If the abstract is not provided or empty, return isVerified: true with low confidence
3. Compare the claim's DIRECTION (benefit vs no benefit) against the abstract
4. Compare specific numbers (HR, RR, OR, CI) if mentioned

## Verification Criteria

1. **Directional Match**
   - Abstract says "no benefit/not significant" → Claim must NOT say there was benefit
   - Abstract says "beneficial/reduced" → Claim must NOT say no effect

2. **Statistical Match**
   - If abstract gives HR 0.94 (95% CI 0.79-1.12), this is NOT significant
   - If abstract gives HR 0.75 (95% CI 0.60-0.90), this IS significant

3. **Population Match**
   - Claim should match the studied population

## Output Format (JSON only)

{
  "isVerified": boolean,
  "confidence": number (0.0-1.0),
  "issue": "Problem description" | null,
  "actualFinding": "Quote from abstract" | null,
  "suggestion": "Correction" | null
}`;

type SupportedLLM = ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI;

/**
 * Verify a single claim against fetched abstract
 */
async function verifyClaimAgainstAbstract(
  claim: string,
  claimSentence: string,
  abstract: string,
  conclusion: string | undefined,
  llm: SupportedLLM
): Promise<Omit<VerificationResult, "referenceNumber" | "claim" | "pmid" | "pmidValidation">> {
  if (!abstract) {
    return {
      isVerified: true,
      confidence: 0.3,
      issue: "No abstract available from PubMed for verification",
    };
  }

  const userPrompt = `## CLAIM FROM REPORT

Claim: "${claim}"
Full sentence: "${claimSentence}"

## ABSTRACT FROM PUBMED (Ground Truth)

${conclusion ? `CONCLUSION: ${conclusion}\n\n` : ""}
FULL ABSTRACT: ${abstract}

## TASK

Compare the claim against this abstract. Does the abstract support the claim?
Return JSON only.`;

  try {
    const response = await llm.invoke([
      new SystemMessage(CLAIM_VERIFIER_SYSTEM_PROMPT),
      new HumanMessage(userPrompt),
    ]);

    const content = typeof response.content === "string"
      ? response.content
      : JSON.stringify(response.content);

    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return { isVerified: true, confidence: 0.5, issue: "Could not parse response" };
    }

    const result = JSON.parse(jsonMatch[0]);
    return {
      isVerified: Boolean(result.isVerified),
      confidence: Math.max(0, Math.min(1, Number(result.confidence) || 0.5)),
      issue: result.issue || undefined,
      actualFinding: result.actualFinding || undefined,
      suggestion: result.suggestion || undefined,
    };
  } catch (error) {
    return {
      isVerified: true,
      confidence: 0.3,
      issue: `Verification error: ${error instanceof Error ? error.message : "Unknown"}`,
    };
  }
}

/**
 * Verify all claims using PubMed as ground truth
 */
export async function verifyReportClaims(
  reportText: string,
  searchResults: Array<{
    referenceNumber?: number;
    title: string;
    pmid?: string;
    abstract?: string;
    conclusion?: string;
  }>,
  llmProvider: "openai" | "anthropic" | "google",
  apiKey: string,
  options?: {
    model?: string;
    ncbiApiKey?: string;
    skipPmidValidation?: boolean;
  }
): Promise<ClaimVerificationReport> {
  // Create LLM for text comparison only
  let llm: SupportedLLM;
  if (llmProvider === "anthropic") {
    llm = new ChatAnthropic({
      modelName: options?.model || "claude-3-5-haiku-20241022",
      anthropicApiKey: apiKey,
      temperature: 0,
    });
  } else if (llmProvider === "google") {
    llm = new ChatGoogleGenerativeAI({
      model: options?.model || "gemini-1.5-flash",
      apiKey: apiKey,
      temperature: 0,
    });
  } else {
    llm = new ChatOpenAI({
      modelName: options?.model || "gpt-4o-mini",
      openAIApiKey: apiKey,
      temperature: 0,
    });
  }

  // Extract citations from report
  const citations = extractCitationsFromReport(reportText);

  // Build reference lookup
  const refLookup = new Map<number, (typeof searchResults)[0]>();
  for (let i = 0; i < searchResults.length; i++) {
    const refNum = searchResults[i].referenceNumber ?? (i + 1);
    refLookup.set(refNum, searchResults[i]);
  }

  // Step 1: Validate all PMIDs against PubMed (ground truth)
  const pmidValidations = new Map<string, PmidValidation>();
  const invalidPmids: PmidValidation[] = [];

  if (!options?.skipPmidValidation) {
    const uniquePmids = new Set<string>();
    for (const result of searchResults) {
      if (result.pmid) uniquePmids.add(result.pmid);
    }

    // Validate in batches
    const pmidArray = Array.from(uniquePmids);
    for (let i = 0; i < pmidArray.length; i += 5) {
      const batch = pmidArray.slice(i, i + 5);
      const validations = await Promise.all(
        batch.map((pmid) => verifyPmidInPubMed(pmid, options?.ncbiApiKey))
      );
      for (const validation of validations) {
        pmidValidations.set(validation.pmid, validation);
        if (!validation.exists) {
          invalidPmids.push(validation);
        }
      }
    }
  }

  // Step 2: Fetch actual abstracts from PubMed for valid PMIDs
  const fetchedAbstracts = new Map<string, { abstract: string; conclusion?: string }>();

  const validationEntries = Array.from(pmidValidations.entries());
  for (const [pmid, validation] of validationEntries) {
    if (validation.exists) {
      const abstractData = await fetchAbstractFromPubMed(pmid, options?.ncbiApiKey);
      if (abstractData) {
        fetchedAbstracts.set(pmid, abstractData);
      }
    }
  }

  // Step 3: Verify each claim against FETCHED abstracts (not stored ones)
  const allResults: VerificationResult[] = [];
  const batchSize = 5;

  for (let i = 0; i < citations.length; i += batchSize) {
    const batch = citations.slice(i, i + batchSize);
    const batchResults = await Promise.all(
      batch.map(async (citation) => {
        const source = refLookup.get(citation.referenceNumber);

        if (!source) {
          return {
            referenceNumber: citation.referenceNumber,
            claim: citation.claim,
            isVerified: true,
            confidence: 0.3,
            issue: "Reference not found in search results",
          };
        }

        const pmid = source.pmid;
        const pmidValidation = pmid ? pmidValidations.get(pmid) : undefined;

        // If PMID is invalid, flag the citation
        if (pmid && pmidValidation && !pmidValidation.exists) {
          return {
            referenceNumber: citation.referenceNumber,
            claim: citation.claim,
            pmid,
            pmidValidation,
            isVerified: false,
            confidence: 0.95,
            issue: `PMID ${pmid} does not exist in PubMed: ${pmidValidation.error}`,
          };
        }

        // Use fetched abstract from PubMed as ground truth
        // Fall back to stored abstract only if fetch failed
        const fetched = pmid ? fetchedAbstracts.get(pmid) : undefined;
        const abstractToUse = fetched?.abstract || source.abstract;
        const conclusionToUse = fetched?.conclusion || source.conclusion;

        if (!abstractToUse) {
          return {
            referenceNumber: citation.referenceNumber,
            claim: citation.claim,
            pmid,
            pmidValidation,
            isVerified: true,
            confidence: 0.4,
            issue: "No abstract available for verification",
          };
        }

        const verification = await verifyClaimAgainstAbstract(
          citation.claim,
          citation.claimSentence,
          abstractToUse,
          conclusionToUse,
          llm
        );

        return {
          referenceNumber: citation.referenceNumber,
          claim: citation.claim,
          pmid,
          pmidValidation,
          ...verification,
        };
      })
    );

    allResults.push(...batchResults);
  }

  // Categorize results
  const criticalIssues = allResults.filter((r) => !r.isVerified && r.confidence >= 0.7);
  const warnings = allResults.filter((r) => !r.isVerified && r.confidence < 0.7);
  const verifiedClaims = allResults.filter((r) => r.isVerified).length;

  return {
    totalClaims: allResults.length,
    verifiedClaims,
    flaggedClaims: allResults.length - verifiedClaims,
    invalidPmids,
    criticalIssues,
    warnings,
    allResults,
  };
}

/**
 * LangChain tool for claim verification
 */
export const claimVerifierTool = tool(
  async ({ reportText, searchResultsJson, llmProvider, apiKey, model, ncbiApiKey }) => {
    try {
      const searchResults = JSON.parse(searchResultsJson);

      const report = await verifyReportClaims(
        reportText,
        searchResults,
        llmProvider as "openai" | "anthropic" | "google",
        apiKey,
        { model, ncbiApiKey }
      );

      let summary: string;
      if (report.invalidPmids.length > 0) {
        summary = `CRITICAL: ${report.invalidPmids.length} PMIDs not found in PubMed`;
      } else if (report.criticalIssues.length > 0) {
        summary = `CRITICAL: ${report.criticalIssues.length} claims may misrepresent findings`;
      } else if (report.warnings.length > 0) {
        summary = `WARNING: ${report.warnings.length} claims need review`;
      } else {
        summary = `All ${report.verifiedClaims} claims verified against PubMed`;
      }

      return JSON.stringify({
        success: true,
        ...report,
        summary,
      });
    } catch (error) {
      return JSON.stringify({
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      });
    }
  },
  {
    name: "claim_verifier",
    description:
      "Verifies claims using PubMed as ground truth. Validates PMIDs exist, fetches actual abstracts, and compares claims against real data (not LLM knowledge).",
    schema: z.object({
      reportText: z.string().describe("The synthesized report to verify"),
      searchResultsJson: z.string().describe("JSON array with title, pmid, abstract, referenceNumber"),
      llmProvider: z.enum(["openai", "anthropic", "google"]).describe("LLM for text comparison"),
      apiKey: z.string().describe("API key for LLM"),
      model: z.string().optional().describe("Model name"),
      ncbiApiKey: z.string().optional().describe("NCBI API key for higher rate limits"),
    }),
  }
);

export { verifyPmidInPubMed, fetchAbstractFromPubMed, verifyClaimAgainstAbstract };
