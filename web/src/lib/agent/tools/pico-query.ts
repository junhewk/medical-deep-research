import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { MESH_MAPPINGS } from "./mesh-mapping";

export interface PicoComponents {
  population: string;
  intervention: string;
  comparison?: string;
  outcome: string;
}

export interface GeneratedQuery {
  pubmedQuery: string;
  meshTerms: string[];
  searchStrategy: string;
  alternativeQueries: string[];
}

function findMeshTerms(text: string): string[] {
  const terms: string[] = [];
  const normalizedText = text.toLowerCase();

  for (const [key, meshTerms] of Object.entries(MESH_MAPPINGS)) {
    const keyNormalized = key.replace(/_/g, " ");
    if (normalizedText.includes(keyNormalized) || normalizedText.includes(key)) {
      terms.push(...meshTerms);
    }
  }

  return [...new Set(terms)];
}

function buildPubMedQuery(components: PicoComponents): GeneratedQuery {
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

  // Intervention
  const interventionMesh = findMeshTerms(components.intervention);
  meshTerms.push(...interventionMesh);
  const interventionQuery =
    interventionMesh.length > 0
      ? `(${interventionMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.intervention}[tiab])`
      : `${components.intervention}[tiab]`;
  queryParts.push(interventionQuery);

  // Comparison (optional)
  if (components.comparison) {
    const comparisonMesh = findMeshTerms(components.comparison);
    meshTerms.push(...comparisonMesh);
    const comparisonQuery =
      comparisonMesh.length > 0
        ? `(${comparisonMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.comparison}[tiab])`
        : `${components.comparison}[tiab]`;
    queryParts.push(comparisonQuery);
  }

  // Outcome
  const outcomeMesh = findMeshTerms(components.outcome);
  meshTerms.push(...outcomeMesh);
  const outcomeQuery =
    outcomeMesh.length > 0
      ? `(${outcomeMesh.map((t) => `"${t}"[MeSH]`).join(" OR ")} OR ${components.outcome}[tiab])`
      : `${components.outcome}[tiab]`;
  queryParts.push(outcomeQuery);

  const pubmedQuery = queryParts.join(" AND ");

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
    `${pubmedQuery} AND (randomized controlled trial[pt] OR clinical trial[pt])`
  );

  // Systematic review filter
  alternativeQueries.push(
    `${pubmedQuery} AND (systematic review[pt] OR meta-analysis[pt])`
  );

  const searchStrategy = `
PICO Search Strategy:

P (Population): ${components.population}
I (Intervention): ${components.intervention}
C (Comparison): ${components.comparison || "N/A"}
O (Outcome): ${components.outcome}

Primary PubMed Query:
${pubmedQuery}

MeSH Terms Identified:
${meshTerms.length > 0 ? meshTerms.join(", ") : "None"}

Alternative Queries:
1. Simple text search: ${alternativeQueries[0]}
2. MeSH-only search: ${alternativeQueries[1] || "N/A"}
3. Clinical trials: ${alternativeQueries[2]}
4. Systematic reviews: ${alternativeQueries[3]}
`.trim();

  return {
    pubmedQuery,
    meshTerms: [...new Set(meshTerms)],
    searchStrategy,
    alternativeQueries,
  };
}

export const picoQueryBuilderTool = tool(
  async ({ population, intervention, comparison, outcome }) => {
    const components: PicoComponents = {
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
      meshTerms: result.meshTerms,
      searchStrategy: result.searchStrategy,
      alternativeQueries: result.alternativeQueries,
    });
  },
  {
    name: "pico_query_builder",
    description:
      "Builds an optimized PubMed search query from PICO components (Population, Intervention, Comparison, Outcome). Automatically maps terms to MeSH headings and generates alternative search strategies.",
    schema: z.object({
      population: z.string().describe("P - Patient/Population/Problem"),
      intervention: z.string().describe("I - Intervention/Exposure"),
      comparison: z.string().optional().describe("C - Comparison (optional)"),
      outcome: z.string().describe("O - Outcome"),
    }),
  }
);

export { buildPubMedQuery, findMeshTerms };
