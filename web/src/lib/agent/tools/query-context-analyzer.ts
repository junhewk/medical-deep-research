import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { createLLM, type LLMProvider, type SupportedLLM } from "./llm-factory";

/**
 * LLM-based semantic context analyzer for PCC/PICO queries
 *
 * Instead of hardcoded keyword lists, uses AI to understand:
 * - Query intent (clinical efficacy, cost-effectiveness, safety, etc.)
 * - Required outcome domains (clinical, economic, patient-reported, etc.)
 * - Comparison semantics (A vs B structure)
 * - Population constraints (numeric thresholds, exclusions)
 */

export type QueryIntent =
  | "clinical_efficacy"
  | "cost_effectiveness"
  | "safety"
  | "diagnostic"
  | "prognostic"
  | "qualitative"
  | "epidemiologic";

export type OutcomeDomain =
  | "clinical"
  | "economic"
  | "patient_reported"
  | "process"
  | "safety";

export interface ComparisonStructure {
  interventionA: {
    term: string;
    synonyms: string[];
  };
  interventionB: {
    term: string;
    synonyms: string[];
  };
}

export interface SearchModifiers {
  studyTypes?: string[];
  dateRange?: {
    recent: boolean;
    years?: number;
  };
  settings?: string[];
}

export interface QueryContextAnalysis {
  queryIntent: QueryIntent[];
  outcomeDomains: OutcomeDomain[];
  comparison?: ComparisonStructure;
  suggestedMeshTerms: string[];
  suggestedTextTerms: string[];
  searchModifiers: SearchModifiers;
  reasoning: string;
}

const CONTEXT_ANALYZER_PROMPT = `You are a medical librarian expert in systematic review search strategy.

Analyze the following research query components and identify:

1. **Query Intent**: What type of evidence is being sought? Select ALL that apply:
   - clinical_efficacy: Treatment effectiveness, clinical outcomes, mortality, morbidity
   - cost_effectiveness: Economic evaluation, cost-benefit, resource utilization
   - safety: Adverse events, complications, harms, side effects
   - diagnostic: Sensitivity, specificity, diagnostic accuracy
   - prognostic: Risk factors, prediction, prognosis
   - qualitative: Experiences, perspectives, barriers, facilitators
   - epidemiologic: Prevalence, incidence, burden of disease

2. **Outcome Domains**: What measurement domains are relevant? Select ALL that apply:
   - clinical: Mortality, morbidity, disease-specific clinical outcomes
   - economic: Costs, length of stay, resource utilization, cost-effectiveness
   - patient_reported: Quality of life, satisfaction, preferences, symptoms
   - process: Adherence, implementation, feasibility, workflow
   - safety: Adverse events, complications, toxicity

3. **Comparison Structure**: If comparing interventions, extract:
   - Intervention A: The main intervention being evaluated
   - Intervention B: The comparator (may be placebo, standard care, or another active treatment)
   - Include common synonyms/variants for each

4. **Suggested MeSH Terms**: Based on the query intent and domains, suggest specific MeSH terms:
   - For economic outcomes: "Length of Stay", "Health Care Costs", "Cost-Benefit Analysis", "Hospital Costs"
   - For safety: "Adverse Effects", "Complications", "Treatment Outcome"
   - For clinical efficacy: "Treatment Outcome", "Mortality", specific disease MeSH
   - For patient-reported: "Quality of Life", "Patient Satisfaction"

5. **Suggested Text Terms**: Free-text terms to search in title/abstract:
   - For economic: "cost", "economic", "resource", "length of stay", "LOS", "readmission", "hospitalization"
   - For safety: "adverse", "complication", "safety", "harm", "side effect"
   - Include domain-specific terminology

6. **Search Modifiers**: Any special search considerations:
   - Study types to include (e.g., RCT, observational, economic evaluation)
   - Date restrictions if relevant
   - Geographic/setting filters if applicable

Return your analysis as valid JSON matching this exact structure:
{
  "queryIntent": ["clinical_efficacy", "cost_effectiveness", ...],
  "outcomeDomains": ["clinical", "economic", ...],
  "comparison": {
    "interventionA": { "term": "...", "synonyms": ["...", "..."] },
    "interventionB": { "term": "...", "synonyms": ["...", "..."] }
  },
  "suggestedMeshTerms": ["MeSH Term 1", "MeSH Term 2", ...],
  "suggestedTextTerms": ["term1", "term2", ...],
  "searchModifiers": {
    "studyTypes": ["RCT", "cost-effectiveness analysis", ...],
    "dateRange": { "recent": true, "years": 5 },
    "settings": ["hospital", "outpatient", ...]
  },
  "reasoning": "Brief explanation of why these choices were made"
}

IMPORTANT:
- Return ONLY valid JSON, no markdown code blocks
- Be comprehensive in suggested terms - better to over-include than miss relevant literature
- Consider the clinical context when suggesting terms`;

// LLM creation is handled by shared llm-factory.ts

function parseJsonResponse(content: string | object): QueryContextAnalysis | null {
  try {
    // Handle if content is already an object
    if (typeof content === "object") {
      return content as QueryContextAnalysis;
    }

    // Clean up common issues
    let cleaned = content.trim();

    // Remove markdown code blocks if present
    if (cleaned.startsWith("```json")) {
      cleaned = cleaned.slice(7);
    } else if (cleaned.startsWith("```")) {
      cleaned = cleaned.slice(3);
    }
    if (cleaned.endsWith("```")) {
      cleaned = cleaned.slice(0, -3);
    }

    cleaned = cleaned.trim();

    return JSON.parse(cleaned) as QueryContextAnalysis;
  } catch (error) {
    console.error("Failed to parse context analysis JSON:", error);
    return null;
  }
}

/**
 * Analyze query context using LLM
 */
export async function analyzeQueryContext(
  components: {
    population?: string;
    concept?: string;
    context?: string;
    intervention?: string;
    comparison?: string;
    outcome?: string;
  },
  options: {
    apiKey: string;
    provider?: LLMProvider;
    model?: string;
  }
): Promise<QueryContextAnalysis | null> {
  const { apiKey, provider = "openai", model } = options;

  const llm = createLLM(provider, apiKey, model);

  const queryDescription = {
    population: components.population || "Not specified",
    concept_or_intervention: components.concept || components.intervention || "Not specified",
    context_or_outcome: components.context || components.outcome || "Not specified",
    comparison: components.comparison || "Not specified",
  };

  try {
    const response = await llm.invoke([
      new SystemMessage(CONTEXT_ANALYZER_PROMPT),
      new HumanMessage(
        `Analyze this medical research query:\n\n${JSON.stringify(queryDescription, null, 2)}`
      ),
    ]);

    const content = typeof response.content === "string" ? response.content : JSON.stringify(response.content);
    return parseJsonResponse(content);
  } catch (error) {
    console.error("Query context analysis failed:", error);
    return null;
  }
}

/**
 * Get MeSH terms based on detected outcome domains
 * Fallback when LLM is not available
 */
export function getOutcomeDomainMeshTerms(domains: OutcomeDomain[]): string[] {
  const domainMeshMap: Record<OutcomeDomain, string[]> = {
    clinical: [
      "Treatment Outcome",
      "Mortality",
      "Morbidity",
      "Recovery of Function",
    ],
    economic: [
      "Length of Stay",
      "Health Care Costs",
      "Cost-Benefit Analysis",
      "Hospital Costs",
      "Health Expenditures",
      "Patient Readmission",
    ],
    patient_reported: [
      "Quality of Life",
      "Patient Satisfaction",
      "Patient Reported Outcome Measures",
      "Health Status",
    ],
    process: [
      "Patient Compliance",
      "Feasibility Studies",
      "Implementation Science",
    ],
    safety: [
      "Adverse Effects",
      "Drug-Related Side Effects and Adverse Reactions",
      "Postoperative Complications",
    ],
  };

  const meshTerms: Set<string> = new Set();
  for (const domain of domains) {
    const terms = domainMeshMap[domain];
    if (terms) {
      terms.forEach((t) => meshTerms.add(t));
    }
  }

  return Array.from(meshTerms);
}

/**
 * Get text search terms based on detected outcome domains
 * Fallback when LLM is not available
 */
export function getOutcomeDomainTextTerms(domains: OutcomeDomain[]): string[] {
  const domainTextMap: Record<OutcomeDomain, string[]> = {
    clinical: ["outcome", "efficacy", "effectiveness", "mortality", "survival"],
    economic: [
      "cost",
      "economic",
      "length of stay",
      "LOS",
      "readmission",
      "resource",
      "hospitalization",
      "expenditure",
    ],
    patient_reported: ["quality of life", "QoL", "satisfaction", "PROM", "PRO"],
    process: ["adherence", "compliance", "implementation", "feasibility"],
    safety: ["adverse", "safety", "complication", "harm", "toxicity", "side effect"],
  };

  const textTerms: Set<string> = new Set();
  for (const domain of domains) {
    const terms = domainTextMap[domain];
    if (terms) {
      terms.forEach((t) => textTerms.add(t));
    }
  }

  return Array.from(textTerms);
}

/**
 * Simple heuristic-based context detection (fallback when no API key)
 */
export function detectContextHeuristic(text: string): {
  intents: QueryIntent[];
  domains: OutcomeDomain[];
} {
  const lowerText = text.toLowerCase();
  const intents: QueryIntent[] = [];
  const domains: OutcomeDomain[] = [];

  // Economic indicators
  const economicKeywords = [
    "cost",
    "economic",
    "resource",
    "length of stay",
    "los",
    "readmission",
    "hospitalization",
    "expenditure",
    "burden",
    "budget",
    "financial",
  ];
  if (economicKeywords.some((kw) => lowerText.includes(kw))) {
    intents.push("cost_effectiveness");
    domains.push("economic");
  }

  // Safety indicators
  const safetyKeywords = [
    "safety",
    "adverse",
    "complication",
    "harm",
    "risk",
    "side effect",
    "toxicity",
  ];
  if (safetyKeywords.some((kw) => lowerText.includes(kw))) {
    intents.push("safety");
    domains.push("safety");
  }

  // Patient-reported indicators
  const proKeywords = ["quality of life", "qol", "satisfaction", "experience", "preference"];
  if (proKeywords.some((kw) => lowerText.includes(kw))) {
    domains.push("patient_reported");
  }

  // Qualitative indicators
  const qualKeywords = [
    "experience",
    "perspective",
    "barrier",
    "facilitator",
    "perception",
    "attitude",
  ];
  if (qualKeywords.some((kw) => lowerText.includes(kw))) {
    intents.push("qualitative");
  }

  // Default to clinical if nothing else detected
  if (intents.length === 0) {
    intents.push("clinical_efficacy");
  }
  if (domains.length === 0) {
    domains.push("clinical");
  }

  return { intents, domains };
}

/**
 * Create a fallback QueryContextAnalysis from text using heuristic detection.
 * Shared helper used by pico-query.ts and pcc-query.ts when LLM analysis fails or is unavailable.
 */
export function createFallbackContextAnalysis(text: string, reasoning: string = "Heuristic detection"): QueryContextAnalysis {
  const heuristic = detectContextHeuristic(text);
  return {
    queryIntent: heuristic.intents,
    outcomeDomains: heuristic.domains,
    suggestedMeshTerms: getOutcomeDomainMeshTerms(heuristic.domains),
    suggestedTextTerms: getOutcomeDomainTextTerms(heuristic.domains),
    searchModifiers: {},
    reasoning,
  };
}

/**
 * LangChain tool wrapper for query context analyzer
 */
export const queryContextAnalyzerTool = tool(
  async ({
    population,
    concept,
    context,
    intervention,
    comparison,
    outcome,
    apiKey,
    provider,
    model,
  }) => {
    // If no API key, use heuristic detection
    if (!apiKey) {
      const allText = [population, concept, context, intervention, comparison, outcome]
        .filter(Boolean)
        .join(" ");

      return JSON.stringify({
        success: true,
        analysis: createFallbackContextAnalysis(allText, "Heuristic detection (no API key provided)"),
        method: "heuristic",
      });
    }

    // Use LLM for semantic analysis
    const analysis = await analyzeQueryContext(
      {
        population: population ?? undefined,
        concept: concept ?? undefined,
        context: context ?? undefined,
        intervention: intervention ?? undefined,
        comparison: comparison ?? undefined,
        outcome: outcome ?? undefined,
      },
      { apiKey, provider: provider ?? undefined, model: model ?? undefined }
    );

    if (!analysis) {
      // Fallback to heuristic if LLM fails
      const allText = [population, concept, context, intervention, comparison, outcome]
        .filter(Boolean)
        .join(" ");

      return JSON.stringify({
        success: true,
        analysis: createFallbackContextAnalysis(allText, "Heuristic fallback (LLM analysis failed)"),
        method: "heuristic_fallback",
      });
    }

    return JSON.stringify({
      success: true,
      analysis,
      method: "llm",
    });
  },
  {
    name: "query_context_analyzer",
    description:
      "Analyzes PICO/PCC query components to determine search intent, outcome domains, and suggest relevant MeSH terms. Use this before building queries to ensure economic/safety/etc. contexts are properly captured in the search strategy.",
    schema: z.object({
      population: z.string().optional().nullable().describe("P - Population/Participants"),
      concept: z.string().optional().nullable().describe("C - Concept (for PCC)"),
      context: z.string().optional().nullable().describe("C - Context (for PCC)"),
      intervention: z.string().optional().nullable().describe("I - Intervention (for PICO)"),
      comparison: z.string().optional().nullable().describe("C - Comparison (for PICO)"),
      outcome: z.string().optional().nullable().describe("O - Outcome (for PICO)"),
      apiKey: z.string().optional().nullable().describe("LLM API key for semantic analysis"),
      provider: z
        .enum(["openai", "anthropic", "google"])
        .optional()
        .nullable()
        .describe("LLM provider"),
      model: z.string().optional().nullable().describe("Model name override"),
    }),
  }
);
