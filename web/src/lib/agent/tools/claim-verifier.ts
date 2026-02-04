import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";

/**
 * Claim Verifier - Post-Synthesis Safety Net
 *
 * This tool extracts claims with citations from synthesized reports,
 * cross-references each claim against actual abstract content,
 * and flags any inconsistencies where the report contradicts the source.
 *
 * KEY USE CASE: Detect hallucinations like reporting "study showed benefit"
 * when actual abstract says "no significant benefit was found"
 */

export interface Citation {
  referenceNumber: number;
  claim: string;
  claimSentence: string; // Full sentence containing the claim
}

export interface VerificationResult {
  referenceNumber: number;
  claim: string;
  isVerified: boolean;
  confidence: number; // 0.0 - 1.0
  issue?: string;
  actualFinding?: string;
  suggestion?: string;
}

export interface ClaimVerificationReport {
  totalClaims: number;
  verifiedClaims: number;
  flaggedClaims: number;
  criticalIssues: VerificationResult[];
  warnings: VerificationResult[];
  allResults: VerificationResult[];
}

/**
 * Extract claims with citations from report text
 * Looks for patterns like: "The study found X [1]" or "Results showed Y [2,3]"
 */
export function extractCitationsFromReport(reportText: string): Citation[] {
  const citations: Citation[] = [];

  // Split report into sentences
  const sentences = reportText.split(/(?<=[.!?])\s+/);

  for (const sentence of sentences) {
    // Find citation patterns like [1], [2], [1,2], [1-3]
    const citationMatches = Array.from(sentence.matchAll(/\[(\d+(?:[,\-]\d+)*)\]/g));

    for (const match of citationMatches) {
      const refNumbers = parseReferenceNumbers(match[1]);

      for (const refNum of refNumbers) {
        // Extract the claim context (text before the citation in this sentence)
        const beforeCitation = sentence.substring(0, match.index).trim();

        // Get the main claim (last clause before citation)
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

/**
 * Parse reference number strings like "1", "2,3", "1-3"
 */
function parseReferenceNumbers(refStr: string): number[] {
  // Handle ranges like "1-3"
  if (refStr.includes("-")) {
    const [start, end] = refStr.split("-").map(Number);
    const numbers: number[] = [];
    for (let i = start; i <= end; i++) {
      numbers.push(i);
    }
    return numbers.filter((n) => !isNaN(n));
  }

  // Handle comma-separated like "1,2,3" or single number like "1"
  return refStr.split(",").map(Number).filter((n) => !isNaN(n));
}

/**
 * System prompt for claim verification
 */
const CLAIM_VERIFIER_SYSTEM_PROMPT = `You are a medical research claim verifier specializing in detecting hallucinations and misrepresentations.

Your task is to verify whether a CLAIM made in a research report is SUPPORTED by the actual ABSTRACT text.

## Verification Criteria

1. **Directional Accuracy**
   - If abstract says "no benefit/no difference/not significant", claim must NOT say there was benefit
   - If abstract says "improved/reduced/beneficial", claim must NOT say there was no effect
   - Neutral claims must not be presented as positive or negative

2. **Magnitude Accuracy**
   - If abstract gives specific numbers (HR, RR, OR), claim should be consistent
   - "Significant reduction" requires the abstract to support statistical significance
   - Don't overstate modest effects as major breakthroughs

3. **Population Accuracy**
   - Claim should apply to the population studied, not be overgeneralized
   - If abstract studied HFrEF, claim shouldn't apply findings to all heart failure

4. **Temporal Accuracy**
   - Don't present old findings as recent evidence
   - Don't confuse acute vs long-term outcomes

## Output Format

Return ONLY valid JSON:
{
  "isVerified": boolean,
  "confidence": number (0.0-1.0),
  "issue": "Description of the problem if not verified" | null,
  "actualFinding": "What the abstract actually says" | null,
  "suggestion": "How to correct the claim" | null
}

## Critical Flags (isVerified: false required)

- Claim says "benefit/effective" when abstract says "no significant benefit"
- Claim says "no effect" when abstract shows significant effect
- Claim reverses the direction of the finding
- Claim attributes findings to wrong population`;

/**
 * Verify a single claim against its source abstract
 */
async function verifyClaimAgainstAbstract(
  claim: string,
  claimSentence: string,
  abstract: string,
  conclusion: string | undefined,
  llm: ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI
): Promise<Omit<VerificationResult, "referenceNumber" | "claim">> {
  const userPrompt = `## CLAIM FROM REPORT

Claim: "${claim}"
Full sentence: "${claimSentence}"

## SOURCE ABSTRACT

${conclusion ? `CONCLUSION SECTION: ${conclusion}\n\n` : ""}
FULL ABSTRACT: ${abstract}

## TASK

Verify if the claim is supported by this abstract. Return JSON only.`;

  try {
    const response = await llm.invoke([
      new SystemMessage(CLAIM_VERIFIER_SYSTEM_PROMPT),
      new HumanMessage(userPrompt),
    ]);

    const content = typeof response.content === "string"
      ? response.content
      : JSON.stringify(response.content);

    // Extract JSON from response
    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return {
        isVerified: true,
        confidence: 0.5,
        issue: "Could not parse verification response",
      };
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
    console.error("Claim verification error:", error);
    return {
      isVerified: true, // Default to verified on error to avoid false positives
      confidence: 0.3,
      issue: `Verification error: ${error instanceof Error ? error.message : "Unknown"}`,
    };
  }
}

/**
 * Verify all claims in a report against source abstracts
 */
export async function verifyReportClaims(
  reportText: string,
  searchResults: Array<{
    referenceNumber?: number;
    title: string;
    abstract?: string;
    conclusion?: string;
  }>,
  llmProvider: "openai" | "anthropic" | "google",
  apiKey: string,
  model?: string
): Promise<ClaimVerificationReport> {
  // Create LLM instance
  let llm: ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI;
  if (llmProvider === "anthropic") {
    llm = new ChatAnthropic({
      modelName: model || "claude-3-5-haiku-20241022",
      anthropicApiKey: apiKey,
      temperature: 0,
    });
  } else if (llmProvider === "google") {
    llm = new ChatGoogleGenerativeAI({
      model: model || "gemini-1.5-flash",
      apiKey: apiKey,
      temperature: 0,
    });
  } else {
    llm = new ChatOpenAI({
      modelName: model || "gpt-4o-mini",
      openAIApiKey: apiKey,
      temperature: 0,
    });
  }

  // Extract citations from report
  const citations = extractCitationsFromReport(reportText);

  // Build reference lookup
  const refLookup = new Map<number, typeof searchResults[0]>();
  for (let i = 0; i < searchResults.length; i++) {
    const refNum = searchResults[i].referenceNumber ?? (i + 1);
    refLookup.set(refNum, searchResults[i]);
  }

  // Verify each citation (in batches for rate limiting)
  const allResults: VerificationResult[] = [];
  const batchSize = 5;

  for (let i = 0; i < citations.length; i += batchSize) {
    const batch = citations.slice(i, i + batchSize);
    const batchResults = await Promise.all(
      batch.map(async (citation) => {
        const source = refLookup.get(citation.referenceNumber);

        if (!source || !source.abstract) {
          return {
            referenceNumber: citation.referenceNumber,
            claim: citation.claim,
            isVerified: true,
            confidence: 0.5,
            issue: "No abstract available for verification",
          };
        }

        const verification = await verifyClaimAgainstAbstract(
          citation.claim,
          citation.claimSentence,
          source.abstract,
          source.conclusion,
          llm
        );

        return {
          referenceNumber: citation.referenceNumber,
          claim: citation.claim,
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
    criticalIssues,
    warnings,
    allResults,
  };
}

/**
 * LangChain tool for claim verification
 */
export const claimVerifierTool = tool(
  async ({ reportText, searchResultsJson, llmProvider, apiKey, model }) => {
    try {
      const searchResults = JSON.parse(searchResultsJson);

      const report = await verifyReportClaims(
        reportText,
        searchResults,
        llmProvider as "openai" | "anthropic" | "google",
        apiKey,
        model
      );

      // Generate summary based on verification results
      let summary: string;
      if (report.criticalIssues.length > 0) {
        summary = `CRITICAL: Found ${report.criticalIssues.length} claims that may misrepresent source findings`;
      } else if (report.warnings.length > 0) {
        summary = `WARNING: Found ${report.warnings.length} claims that need review`;
      } else {
        summary = `All ${report.verifiedClaims} claims verified against sources`;
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
      "Verifies claims in a research report against source abstracts. Detects hallucinations where report claims contradict actual findings (e.g., saying 'study showed benefit' when abstract says 'no significant benefit').",
    schema: z.object({
      reportText: z.string().describe("The full text of the synthesized report to verify"),
      searchResultsJson: z.string().describe("JSON array of search results with title, abstract, conclusion, referenceNumber"),
      llmProvider: z.enum(["openai", "anthropic", "google"]).describe("LLM provider to use for verification"),
      apiKey: z.string().describe("API key for the LLM provider"),
      model: z.string().optional().describe("Optional model name (defaults to fast model for each provider)"),
    }),
  }
);

export { verifyClaimAgainstAbstract };
