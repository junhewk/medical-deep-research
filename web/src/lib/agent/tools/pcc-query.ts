import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { findMeshTerms } from "./mesh-mapping";

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
  meshTerms: string[];
  searchStrategy: string;
  alternativeQueries: string[];
}

function buildPccPubMedQuery(components: PccQueryInput): GeneratedPccQuery {
  const meshTerms: string[] = [];
  const queryParts: string[] = [];

  // Population
  const populationMesh = findMeshTerms(components.population);
  meshTerms.push(...populationMesh);
  const populationQuery =
    populationMesh.length > 0
      ? `(${populationMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.population}[tiab])`
      : `${components.population}[tiab]`;
  queryParts.push(populationQuery);

  // Concept (phenomenon of interest)
  const conceptMesh = findMeshTerms(components.concept);
  meshTerms.push(...conceptMesh);
  const conceptQuery =
    conceptMesh.length > 0
      ? `(${conceptMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.concept}[tiab])`
      : `${components.concept}[tiab]`;
  queryParts.push(conceptQuery);

  // Context
  const contextMesh = findMeshTerms(components.context);
  meshTerms.push(...contextMesh);
  const contextQuery =
    contextMesh.length > 0
      ? `(${contextMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.context}[tiab])`
      : `${components.context}[tiab]`;
  queryParts.push(contextQuery);

  const pubmedQuery = queryParts.join(" AND ");

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
    `${pubmedQuery} AND (qualitative research[MeSH] OR qualitative[tiab] OR phenomenolog*[tiab] OR grounded theory[tiab] OR ethnograph*[tiab])`
  );

  // Scoping review filter
  alternativeQueries.push(
    `${pubmedQuery} AND (scoping review[tiab] OR mapping review[tiab] OR systematic map[tiab])`
  );

  const searchStrategy = `
PCC Search Strategy (for Scoping Reviews / Qualitative Research):

P (Population): ${components.population}
C (Concept): ${components.concept}
C (Context): ${components.context}

Primary PubMed Query:
${pubmedQuery}

MeSH Terms Identified:
${meshTerms.length > 0 ? meshTerms.join(", ") : "None"}

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
    meshTerms: Array.from(new Set(meshTerms)),
    searchStrategy,
    alternativeQueries,
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
      meshTerms: result.meshTerms,
      searchStrategy: result.searchStrategy,
      alternativeQueries: result.alternativeQueries,
    });
  },
  {
    name: "pcc_query_builder",
    description:
      "Builds an optimized PubMed search query from PCC components (Population, Concept, Context). Used for scoping reviews and qualitative research questions. Automatically maps terms to MeSH headings.",
    schema: z.object({
      population: z.string().describe("P - Population/Participants"),
      concept: z.string().describe("C - Concept/Phenomenon of interest"),
      context: z.string().describe("C - Context/Setting"),
    }),
  }
);

export { buildPccPubMedQuery };
