import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { findMeshTerms } from "./mesh-mapping";
import {
  type QueryBlock,
  buildBlockQuery,
  formatQueryForDisplay,
  extractTextWords,
} from "./query-formatter";

/**
 * PICO components for query building (stricter version with required fields).
 * For API input types, use PicoComponents from @/types/index.ts
 */
export interface PicoQueryInput {
  population: string;
  intervention: string;
  comparison?: string;
  outcome: string;
}

/**
 * Parsed population criteria with numeric thresholds and exclusions
 */
export interface ParsedPopulationCriteria {
  basePopulation: string;
  numericCriteria: Array<{
    parameter: string;
    operator: string;
    value: number;
    unit?: string;
  }>;
  exclusions: string[];
}

/**
 * Parse population string to extract numeric criteria like LVEF >= 50%, age > 65
 */
export function parsePopulationCriteria(population: string): ParsedPopulationCriteria {
  const numericCriteria: ParsedPopulationCriteria["numericCriteria"] = [];

  // Define all patterns with their parameter configurations
  const patternConfigs = [
    // LVEF patterns: "LVEF >= 50%", "LVEF>50", "EF < 40%", "ejection fraction >= 50"
    {
      patterns: [
        /\b(?:LVEF|EF|ejection\s+fraction)\s*([><=]+)\s*(\d+)\s*%?/gi,
        /\b(?:LVEF|EF)\s*(?:of\s+)?([><=]+)\s*(\d+)/gi,
      ],
      parameter: "LVEF",
      unit: "%",
      parseValue: (v: string) => parseInt(v, 10),
    },
    // Age patterns: "age > 65", "age >= 18", "adults > 60 years"
    {
      patterns: [
        /\bage\s*([><=]+)\s*(\d+)\s*(?:years?|y)?/gi,
        /\badults?\s*([><=]+)\s*(\d+)/gi,
      ],
      parameter: "age",
      unit: "years",
      parseValue: (v: string) => parseInt(v, 10),
    },
    // BMI patterns: "BMI > 30", "BMI >= 25"
    {
      patterns: [/\bBMI\s*([><=]+)\s*(\d+(?:\.\d+)?)/gi],
      parameter: "BMI",
      unit: "kg/m²",
      parseValue: (v: string) => parseFloat(v),
    },
    // eGFR patterns: "eGFR < 60"
    {
      patterns: [/\beGFR\s*([><=]+)\s*(\d+)/gi],
      parameter: "eGFR",
      unit: "mL/min/1.73m²",
      parseValue: (v: string) => parseInt(v, 10),
    },
  ];

  // Extract numeric criteria from all pattern configurations
  for (const config of patternConfigs) {
    for (const pattern of config.patterns) {
      const matches = Array.from(population.matchAll(pattern));
      for (const match of matches) {
        numericCriteria.push({
          parameter: config.parameter,
          operator: match[1],
          value: config.parseValue(match[2]),
          unit: config.unit,
        });
      }
    }
  }

  // Generate exclusions based on criteria
  const exclusions = generateExclusionKeywords(numericCriteria);

  return {
    basePopulation: population,
    numericCriteria,
    exclusions,
  };
}

/**
 * Generate exclusion keywords based on parsed numeric criteria
 */
export function generateExclusionKeywords(
  criteria: ParsedPopulationCriteria["numericCriteria"]
): string[] {
  const exclusions: string[] = [];

  for (const criterion of criteria) {
    if (criterion.parameter === "LVEF") {
      // If looking for preserved EF (>= 40-50%), exclude reduced EF terms
      if (
        (criterion.operator === ">=" || criterion.operator === ">") &&
        criterion.value >= 40
      ) {
        exclusions.push(
          "HFrEF",
          "reduced ejection fraction",
          "systolic dysfunction",
          "LVEF<40",
          "LVEF < 40",
          "EF<40",
          "severe LV dysfunction"
        );
      }
      // If looking for reduced EF (< 40%), exclude preserved EF terms
      if (
        (criterion.operator === "<" || criterion.operator === "<=") &&
        criterion.value <= 45
      ) {
        exclusions.push(
          "HFpEF",
          "preserved ejection fraction",
          "diastolic dysfunction",
          "LVEF>50",
          "LVEF >= 50",
          "normal ejection fraction"
        );
      }
      // Mid-range EF (40-49%)
      if (
        criterion.value >= 40 &&
        criterion.value <= 49 &&
        (criterion.operator === ">=" || criterion.operator === "<=")
      ) {
        exclusions.push("HFrEF", "severe systolic dysfunction");
      }
    }

    if (criterion.parameter === "eGFR") {
      // If looking for normal kidney function (>= 60), exclude CKD terms
      if (
        (criterion.operator === ">=" || criterion.operator === ">") &&
        criterion.value >= 60
      ) {
        exclusions.push(
          "end-stage renal disease",
          "ESRD",
          "dialysis",
          "CKD stage 4",
          "CKD stage 5"
        );
      }
      // If looking for reduced kidney function, exclude normal
      if (criterion.operator === "<" && criterion.value <= 60) {
        exclusions.push("normal renal function", "preserved kidney function");
      }
    }
  }

  // Remove duplicates
  return Array.from(new Set(exclusions));
}

export interface GeneratedPicoQuery {
  pubmedQuery: string;
  professionalQuery: string;
  formattedQuery: string;
  meshTerms: string[];
  searchStrategy: string;
  alternativeQueries: string[];
  queryBlocks: QueryBlock[];
}

function buildPubMedQuery(components: PicoQueryInput): GeneratedPicoQuery {
  const meshTerms: string[] = [];
  const queryBlocks: QueryBlock[] = [];

  // Parse population for numeric criteria and exclusions
  const parsedPopulation = parsePopulationCriteria(components.population);

  // Population (P)
  const populationMesh = findMeshTerms(components.population);
  meshTerms.push(...populationMesh);
  const populationTextWords = extractTextWords(components.population, populationMesh);
  const populationBlock: QueryBlock = {
    concept: "P",
    label: "Population",
    meshTerms: populationMesh,
    textWords: populationTextWords,
    combined: buildBlockQuery(populationMesh, populationTextWords),
  };
  queryBlocks.push(populationBlock);

  // Intervention (I)
  const interventionMesh = findMeshTerms(components.intervention);
  meshTerms.push(...interventionMesh);
  const interventionTextWords = extractTextWords(components.intervention, interventionMesh);
  const interventionBlock: QueryBlock = {
    concept: "I",
    label: "Intervention",
    meshTerms: interventionMesh,
    textWords: interventionTextWords,
    combined: buildBlockQuery(interventionMesh, interventionTextWords),
  };
  queryBlocks.push(interventionBlock);

  // Comparison (C) - optional
  if (components.comparison) {
    const comparisonMesh = findMeshTerms(components.comparison);
    meshTerms.push(...comparisonMesh);
    const comparisonTextWords = extractTextWords(components.comparison, comparisonMesh);
    const comparisonBlock: QueryBlock = {
      concept: "C",
      label: "Comparison",
      meshTerms: comparisonMesh,
      textWords: comparisonTextWords,
      combined: buildBlockQuery(comparisonMesh, comparisonTextWords),
    };
    queryBlocks.push(comparisonBlock);
  }

  // Outcome (O)
  const outcomeMesh = findMeshTerms(components.outcome);
  meshTerms.push(...outcomeMesh);
  const outcomeTextWords = extractTextWords(components.outcome, outcomeMesh);
  const outcomeBlock: QueryBlock = {
    concept: "O",
    label: "Outcome",
    meshTerms: outcomeMesh,
    textWords: outcomeTextWords,
    combined: buildBlockQuery(outcomeMesh, outcomeTextWords),
  };
  queryBlocks.push(outcomeBlock);

  // Build the professional query by combining all blocks
  const validBlocks = queryBlocks.filter((b) => b.combined);
  let professionalQuery = validBlocks.map((b) => b.combined).join(" AND ");

  // Add exclusion clause using NOT operator if we have population-based exclusions
  if (parsedPopulation.exclusions.length > 0) {
    const exclusionClause = parsedPopulation.exclusions
      .map((term) => `"${term}"[tiab]`)
      .join(" OR ");
    professionalQuery = `(${professionalQuery}) NOT (${exclusionClause})`;
  }

  // Format for display with proper line breaks
  const formattedQuery = formatQueryForDisplay(professionalQuery);

  // Legacy pubmedQuery format (for backwards compatibility)
  const pubmedQuery = professionalQuery;

  // Generate alternative queries
  const alternativeQueries: string[] = [];

  // Simple title/abstract search
  const simpleTerms = [
    components.population,
    components.intervention,
    components.comparison,
    components.outcome,
  ]
    .filter(Boolean)
    .join(" AND ");
  alternativeQueries.push(`(${simpleTerms})[tiab]`);

  // MeSH only search
  if (meshTerms.length > 0) {
    alternativeQueries.push(meshTerms.map((t) => `"${t}"[MeSH]`).join(" AND "));
  }

  // Clinical trial filter
  alternativeQueries.push(
    `${professionalQuery} AND (randomized controlled trial[pt] OR clinical trial[pt])`
  );

  // Systematic review filter
  alternativeQueries.push(
    `${professionalQuery} AND (systematic review[pt] OR meta-analysis[pt])`
  );

  // Include numeric criteria info if found
  const numericCriteriaInfo = parsedPopulation.numericCriteria.length > 0
    ? `\nNumeric Criteria Detected:\n${parsedPopulation.numericCriteria
        .map((c) => `  - ${c.parameter} ${c.operator} ${c.value}${c.unit || ""}`)
        .join("\n")}`
    : "";

  const exclusionsInfo = parsedPopulation.exclusions.length > 0
    ? `\nExclusion Terms (population mismatch prevention):\n${parsedPopulation.exclusions.map((e) => `  - "${e}"`).join("\n")}`
    : "";

  const searchStrategy = `
PICO Search Strategy:

P (Population): ${components.population}
I (Intervention): ${components.intervention}
C (Comparison): ${components.comparison || "N/A"}
O (Outcome): ${components.outcome}
${numericCriteriaInfo}
${exclusionsInfo}

Primary PubMed Query:
${formattedQuery}

MeSH Terms Identified:
${meshTerms.length > 0 ? meshTerms.join(", ") : "None"}

Query Blocks:
${queryBlocks.map((b) => `${b.concept} (${b.label}): ${b.combined}`).join("\n")}

Alternative Queries:
1. Simple text search: ${alternativeQueries[0]}
2. MeSH-only search: ${alternativeQueries[1] || "N/A"}
3. Clinical trials: ${alternativeQueries[2]}
4. Systematic reviews: ${alternativeQueries[3]}
`.trim();

  return {
    pubmedQuery,
    professionalQuery,
    formattedQuery,
    meshTerms: Array.from(new Set(meshTerms)),
    searchStrategy,
    alternativeQueries,
    queryBlocks,
  };
}

export const picoQueryBuilderTool = tool(
  async ({ population, intervention, comparison, outcome }): Promise<string> => {
    const components: PicoQueryInput = {
      population,
      intervention,
      comparison,
      outcome,
    };

    const result = buildPubMedQuery(components);

    return JSON.stringify({
      success: true,
      components: {
        population,
        intervention,
        comparison: comparison || null,
        outcome,
      },
      generatedQuery: result.pubmedQuery,
      professionalQuery: result.professionalQuery,
      formattedQuery: result.formattedQuery,
      meshTerms: result.meshTerms,
      searchStrategy: result.searchStrategy,
      alternativeQueries: result.alternativeQueries,
      queryBlocks: result.queryBlocks,
    });
  },
  {
    name: "pico_query_builder",
    description:
      "Builds an optimized PubMed search query from PICO components (Population, Intervention, Comparison, Outcome). Automatically maps terms to MeSH headings and generates professional search queries with proper field tags.",
    schema: z.object({
      population: z.string().describe("P - Patient/Population/Problem"),
      intervention: z.string().describe("I - Intervention/Exposure"),
      comparison: z.string().optional().describe("C - Comparison (optional)"),
      outcome: z.string().describe("O - Outcome"),
    }),
  }
);

export { buildPubMedQuery };
