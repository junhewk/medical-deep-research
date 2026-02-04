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
  const professionalQuery = validBlocks.map((b) => b.combined).join(" AND ");

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

  const searchStrategy = `
PICO Search Strategy:

P (Population): ${components.population}
I (Intervention): ${components.intervention}
C (Comparison): ${components.comparison || "N/A"}
O (Outcome): ${components.outcome}

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
