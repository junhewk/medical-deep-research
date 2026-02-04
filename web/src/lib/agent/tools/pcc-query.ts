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
 * PCC components for query building (stricter version with required fields).
 * For API input types, use PccComponents from @/types/index.ts
 */
export interface PccQueryInput {
  population: string;
  concept: string;
  context: string;
}

export interface GeneratedPccQuery {
  pubmedQuery: string;
  professionalQuery: string;
  formattedQuery: string;
  meshTerms: string[];
  searchStrategy: string;
  alternativeQueries: string[];
  queryBlocks: QueryBlock[];
}

function buildPccPubMedQuery(components: PccQueryInput): GeneratedPccQuery {
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

  // Concept (phenomenon of interest)
  const conceptMesh = findMeshTerms(components.concept);
  meshTerms.push(...conceptMesh);
  const conceptTextWords = extractTextWords(components.concept, conceptMesh);
  const conceptBlock: QueryBlock = {
    concept: "Concept",
    label: "Concept",
    meshTerms: conceptMesh,
    textWords: conceptTextWords,
    combined: buildBlockQuery(conceptMesh, conceptTextWords),
  };
  queryBlocks.push(conceptBlock);

  // Context
  const contextMesh = findMeshTerms(components.context);
  meshTerms.push(...contextMesh);
  const contextTextWords = extractTextWords(components.context, contextMesh);
  const contextBlock: QueryBlock = {
    concept: "Context",
    label: "Context",
    meshTerms: contextMesh,
    textWords: contextTextWords,
    combined: buildBlockQuery(contextMesh, contextTextWords),
  };
  queryBlocks.push(contextBlock);

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
  const simpleTerms = [components.population, components.concept, components.context]
    .filter(Boolean)
    .join(" AND ");
  alternativeQueries.push(`(${simpleTerms})[tiab]`);

  // MeSH only search
  if (meshTerms.length > 0) {
    alternativeQueries.push(meshTerms.map((t) => `"${t}"[MeSH]`).join(" AND "));
  }

  // Qualitative research filter
  alternativeQueries.push(
    `${professionalQuery} AND (qualitative research[MeSH] OR qualitative[tiab] OR phenomenolog*[tiab] OR grounded theory[tiab] OR ethnograph*[tiab])`
  );

  // Scoping review filter
  alternativeQueries.push(
    `${professionalQuery} AND (scoping review[tiab] OR mapping review[tiab] OR systematic map[tiab])`
  );

  const searchStrategy = `
PCC Search Strategy (for Scoping Reviews / Qualitative Research):

P (Population): ${components.population}
C (Concept): ${components.concept}
C (Context): ${components.context}

Primary PubMed Query:
${formattedQuery}

MeSH Terms Identified:
${meshTerms.length > 0 ? meshTerms.join(", ") : "None"}

Query Blocks:
${queryBlocks.map((b) => `${b.concept} (${b.label}): ${b.combined}`).join("\n")}

Alternative Queries:
1. Simple text search: ${alternativeQueries[0]}
2. MeSH-only search: ${alternativeQueries[1] || "N/A"}
3. Qualitative studies: ${alternativeQueries[2]}
4. Scoping reviews: ${alternativeQueries[3]}

Note: PCC framework is typically used for:
- Scoping reviews
- Qualitative/mixed-methods reviews
- Exploratory questions where outcomes are less defined
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

export const pccQueryBuilderTool = tool(
  async ({ population, concept, context }): Promise<string> => {
    const components: PccQueryInput = {
      population,
      concept,
      context,
    };

    const result = buildPccPubMedQuery(components);

    return JSON.stringify({
      success: true,
      components: {
        population,
        concept,
        context,
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
    name: "pcc_query_builder",
    description:
      "Builds an optimized PubMed search query from PCC components (Population, Concept, Context). Used for scoping reviews and qualitative research questions. Automatically maps terms to MeSH headings and generates professional search queries.",
    schema: z.object({
      population: z.string().describe("P - Population/Participants"),
      concept: z.string().describe("C - Concept/Phenomenon of interest"),
      context: z.string().describe("C - Context/Setting"),
    }),
  }
);

export { buildPccPubMedQuery };
