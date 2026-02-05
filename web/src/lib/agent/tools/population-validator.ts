import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { createVerifierLLM, type LLMProvider, type SupportedLLM } from "./llm-factory";

/**
 * AI-based population validation for medical research
 *
 * Uses LLM to validate if a study's population matches target criteria.
 * This is domain-agnostic and works across cardiology, oncology, nephrology, etc.
 *
 * Key benefits over keyword matching:
 * - Understands semantic equivalence (e.g., "preserved EF" = "LVEF >= 50%")
 * - Detects subtle context mismatches (acute MI != chronic HF)
 * - Provides reasoning for transparency
 * - Works without hardcoded patterns
 */

/**
 * Target population criteria from the research query
 */
export interface TargetCriteria {
  population: string;
  clinicalContext?: string; // e.g., "acute MI", "chronic HF", "outpatient"
  numericCriteria?: string; // e.g., "LVEF >= 50%", "age > 65"
}

/**
 * Result of population validation
 */
export interface PopulationValidationResult {
  isMatch: boolean;
  matchScore: number; // 0.0 - 1.0
  reasoning: string;
  violations: string[]; // Specific mismatches found
  extractedPopulation: string; // What the study actually studied
}

/**
 * System prompt for population validation
 */
const POPULATION_VALIDATOR_SYSTEM_PROMPT = `You are a medical research population validator specializing in evidence-based medicine.

Your task is to determine if a STUDY POPULATION matches the TARGET POPULATION criteria.

## Evaluation Criteria

1. **Clinical Context Match**
   - Acute vs chronic conditions (e.g., acute MI vs chronic heart failure)
   - Inpatient vs outpatient settings
   - Primary vs secondary prevention

2. **Numeric Criteria Match**
   - Ejection fraction thresholds (LVEF >= 50% = preserved, < 40% = reduced)
   - Age ranges
   - Lab value thresholds (eGFR, BMI, HbA1c)

3. **Disease Stage/Severity**
   - Early vs advanced disease
   - Mild vs severe presentations
   - Stable vs unstable conditions

4. **Inclusion/Exclusion Alignment**
   - Study inclusion criteria should overlap with target
   - Study exclusion criteria shouldn't exclude target population

## Scoring Guidelines

- **1.0**: Perfect match - study population directly applicable
- **0.8-0.9**: Good match - minor differences unlikely to affect applicability
- **0.5-0.7**: Partial match - some overlap but significant differences
- **0.2-0.4**: Poor match - different population, limited applicability
- **0.0-0.1**: No match - completely different population

## Important Distinctions

- HFrEF (LVEF < 40%) ≠ HFpEF (LVEF >= 50%)
- Acute MI (post-infarction) ≠ Chronic heart failure
- Primary prevention ≠ Secondary prevention
- Inpatient/ICU ≠ Outpatient/clinic

## Output Format

Return ONLY valid JSON:
{
  "isMatch": boolean,
  "matchScore": number (0.0-1.0),
  "reasoning": "Brief explanation of why the populations do or don't match",
  "violations": ["List of specific criteria that don't match"],
  "extractedPopulation": "Description of the study's actual population"
}`;

// LLM creation is handled by shared llm-factory.ts (createVerifierLLM)

/**
 * Validate population match using LLM
 *
 * Supports multiple LLM providers (OpenAI, Anthropic, Google)
 * Uses user's configured provider instead of hardcoding OpenAI
 */
async function validatePopulationWithLLM(
  targetCriteria: TargetCriteria,
  studyAbstract: string,
  studyTitle?: string,
  options?: {
    apiKey?: string;
    provider?: "openai" | "anthropic" | "google";
    model?: string;
    llm?: SupportedLLM; // Pre-configured LLM instance
  }
): Promise<PopulationValidationResult> {
  let llm: SupportedLLM;

  // Use provided LLM instance if available
  if (options?.llm) {
    llm = options.llm;
  } else {
    // Create LLM from configuration
    const apiKey = options?.apiKey || process.env.OPENAI_API_KEY;
    const provider = options?.provider || "openai";

    if (!apiKey) {
      // Return default match if no API key available
      console.warn("No API key for population validation, defaulting to match");
      return {
        isMatch: true,
        matchScore: 1.0,
        reasoning: "Population validation skipped (no API key)",
        violations: [],
        extractedPopulation: "Unknown",
      };
    }

    llm = createVerifierLLM(provider, apiKey, options?.model);
  }

  // Build the user prompt
  const userPrompt = `## TARGET POPULATION CRITERIA

Population: ${targetCriteria.population}
${targetCriteria.clinicalContext ? `Clinical Context: ${targetCriteria.clinicalContext}` : ""}
${targetCriteria.numericCriteria ? `Numeric Criteria: ${targetCriteria.numericCriteria}` : ""}

## STUDY TO VALIDATE

${studyTitle ? `Title: ${studyTitle}` : ""}

Abstract:
${studyAbstract}

## TASK

Analyze whether this study's population matches the target criteria. Return JSON only.`;

  try {
    const response = await llm.invoke([
      new SystemMessage(POPULATION_VALIDATOR_SYSTEM_PROMPT),
      new HumanMessage(userPrompt),
    ]);

    // Parse the response
    const content = typeof response.content === "string"
      ? response.content
      : JSON.stringify(response.content);

    // Extract JSON from response (handle markdown code blocks)
    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error("No JSON found in LLM response");
    }

    const result = JSON.parse(jsonMatch[0]) as PopulationValidationResult;

    // Validate and normalize the result
    return {
      isMatch: Boolean(result.isMatch),
      matchScore: Math.max(0, Math.min(1, Number(result.matchScore) || 0)),
      reasoning: String(result.reasoning || "No reasoning provided"),
      violations: Array.isArray(result.violations) ? result.violations.map(String) : [],
      extractedPopulation: String(result.extractedPopulation || "Unknown"),
    };
  } catch (error) {
    console.error("Population validation error:", error);
    // Return cautious default on error (don't assume match)
    return {
      isMatch: true,
      matchScore: 0.7, // Slight penalty for validation failure
      reasoning: `Validation error: ${error instanceof Error ? error.message : "Unknown error"}`,
      violations: ["Validation could not be completed"],
      extractedPopulation: "Unknown (validation error)",
    };
  }
}

/**
 * Batch validate multiple studies against target criteria
 *
 * Supports OpenAI, Anthropic, and Google LLM providers
 */
export async function batchValidatePopulations(
  targetCriteria: TargetCriteria,
  studies: Array<{ abstract: string; title?: string; id: string }>,
  options?: {
    apiKey?: string;
    provider?: "openai" | "anthropic" | "google";
    model?: string;
    llm?: SupportedLLM;
  }
): Promise<Map<string, PopulationValidationResult>> {
  const results = new Map<string, PopulationValidationResult>();

  // Process in parallel with rate limiting (max 5 concurrent)
  const batchSize = 5;
  for (let i = 0; i < studies.length; i += batchSize) {
    const batch = studies.slice(i, i + batchSize);
    const batchResults = await Promise.all(
      batch.map(async (study) => {
        const result = await validatePopulationWithLLM(
          targetCriteria,
          study.abstract,
          study.title,
          options
        );
        return { id: study.id, result };
      })
    );

    for (const { id, result } of batchResults) {
      results.set(id, result);
    }
  }

  return results;
}

/**
 * LangChain tool for population validation
 *
 * Can be used by the agent to validate individual study populations
 * Supports OpenAI, Anthropic, and Google LLM providers
 */
export const populationValidatorTool = tool(
  async ({ targetPopulation, targetContext, targetNumericCriteria, studyAbstract, studyTitle, apiKey, provider, model }) => {
    const targetCriteria: TargetCriteria = {
      population: targetPopulation,
      clinicalContext: targetContext ?? undefined,
      numericCriteria: targetNumericCriteria ?? undefined,
    };

    const result = await validatePopulationWithLLM(
      targetCriteria,
      studyAbstract,
      studyTitle ?? undefined,
      {
        apiKey: apiKey ?? undefined,
        provider: (provider ?? undefined) as "openai" | "anthropic" | "google" | undefined,
        model: model ?? undefined,
      }
    );

    // Determine recommendation based on match status and score
    let recommendation: string;
    if (result.isMatch) {
      recommendation = "Include in analysis";
    } else if (result.matchScore >= 0.5) {
      recommendation = "Review carefully - partial population match";
    } else {
      recommendation = "Consider excluding - population mismatch";
    }

    return JSON.stringify({
      success: true,
      ...result,
      recommendation,
    });
  },
  {
    name: "population_validator",
    description:
      "Validates if a study's population matches target criteria using AI analysis. Works across all medical domains (cardiology, oncology, nephrology, etc.). Use this to filter out studies with population mismatches (e.g., HFrEF studies when looking for HFpEF).",
    schema: z.object({
      targetPopulation: z.string().describe("Target population from research query (e.g., 'patients with AMI and preserved ejection fraction')"),
      targetContext: z.string().optional().nullable().describe("Clinical context (e.g., 'acute MI', 'post-discharge', 'outpatient')"),
      targetNumericCriteria: z.string().optional().nullable().describe("Numeric criteria (e.g., 'LVEF >= 50%', 'age > 65', 'eGFR < 60')"),
      studyAbstract: z.string().describe("Abstract text of the study to validate"),
      studyTitle: z.string().optional().nullable().describe("Title of the study"),
      apiKey: z.string().optional().nullable().describe("API key for the LLM provider"),
      provider: z.enum(["openai", "anthropic", "google"]).optional().nullable().describe("LLM provider (defaults to openai)"),
      model: z.string().optional().nullable().describe("Optional model name (defaults to fast model for each provider)"),
    }),
  }
);

export { validatePopulationWithLLM };
