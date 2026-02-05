import { z } from "zod";
import { tool } from "@langchain/core/tools";
import { findMeshTerms } from "./mesh-mapping";
import {
  type QueryBlock,
  buildBlockQuery,
  formatQueryForDisplay,
  extractTextWords,
} from "./query-formatter";
import {
  batchLookupMeshTerms,
  extractMeshLabels,
  extractKeyPhrases,
  type MeshLookupResult,
} from "./mesh-resolver";
import {
  analyzeQueryContext,
  createFallbackContextAnalysis,
  type QueryContextAnalysis,
} from "./query-context-analyzer";

/**
 * PCC components for query building (stricter version with required fields).
 * For API input types, use PccComponents from @/types/index.ts
 */
export interface PccQueryInput {
  population: string;
  concept: string;
  context: string;
}

export interface EnhancedPccQueryOptions {
  apiKey?: string;
  provider?: "openai" | "anthropic" | "google";
  model?: string;
  useDynamicMesh?: boolean;
  useContextAnalysis?: boolean;
}

export interface GeneratedPccQuery {
  pubmedQuery: string;
  professionalQuery: string;
  formattedQuery: string;
  meshTerms: string[];
  searchStrategy: string;
  alternativeQueries: string[];
  queryBlocks: QueryBlock[];
  contextAnalysis?: QueryContextAnalysis;
  dynamicMeshLookup?: Record<string, MeshLookupResult[]>;
}

/**
 * Build PCC PubMed query with optional enhanced features
 */
async function buildPccPubMedQueryEnhanced(
  components: PccQueryInput,
  options?: EnhancedPccQueryOptions
): Promise<GeneratedPccQuery> {
  let contextAnalysis: QueryContextAnalysis | undefined;
  let dynamicMeshLookup: Record<string, MeshLookupResult[]> | undefined;

  // 1. Analyze context with LLM if API key available
  if (options?.useContextAnalysis !== false && options?.apiKey) {
    try {
      const analysis = await analyzeQueryContext(
        {
          population: components.population,
          concept: components.concept,
          context: components.context,
        },
        {
          apiKey: options.apiKey,
          provider: options.provider,
          model: options.model,
        }
      );
      if (analysis) {
        contextAnalysis = analysis;
      }
    } catch (error) {
      console.warn("Context analysis failed, using fallback:", error);
    }
  }

  // 2. Fallback: Use heuristic detection if LLM analysis not available
  if (!contextAnalysis) {
    const allText = `${components.population} ${components.concept} ${components.context}`;
    contextAnalysis = createFallbackContextAnalysis(allText);
  }

  // 3. Dynamic MeSH lookup if enabled
  if (options?.useDynamicMesh !== false) {
    try {
      // Extract key phrases for lookup
      const phrasesToLookup = [
        ...extractKeyPhrases(components.population),
        ...extractKeyPhrases(components.concept),
        ...extractKeyPhrases(components.context),
        // Include LLM-suggested terms if available
        ...(contextAnalysis?.suggestedMeshTerms || []),
      ];

      // Deduplicate
      const uniquePhrases = Array.from(new Set(phrasesToLookup));

      // Lookup MeSH terms dynamically
      dynamicMeshLookup = await batchLookupMeshTerms(uniquePhrases.slice(0, 15));
    } catch (error) {
      console.warn("Dynamic MeSH lookup failed:", error);
    }
  }

  // 4. Combine all MeSH terms
  const allMeshTerms: string[] = [];

  // Add static mappings
  const populationStaticMesh = findMeshTerms(components.population);
  const conceptStaticMesh = findMeshTerms(components.concept);
  const contextStaticMesh = findMeshTerms(components.context);
  allMeshTerms.push(...populationStaticMesh, ...conceptStaticMesh, ...contextStaticMesh);

  // Add dynamic lookup results
  if (dynamicMeshLookup) {
    const dynamicLabels = extractMeshLabels(dynamicMeshLookup);
    allMeshTerms.push(...dynamicLabels);
  }

  // Add context-suggested MeSH terms
  if (contextAnalysis?.suggestedMeshTerms) {
    allMeshTerms.push(...contextAnalysis.suggestedMeshTerms);
  }

  // Deduplicate
  const uniqueMeshTerms = Array.from(new Set(allMeshTerms));

  // 5. Build query blocks
  const queryBlocks: QueryBlock[] = [];

  // Population block
  const populationMesh = [
    ...populationStaticMesh,
    ...(dynamicMeshLookup ? extractMeshLabels(
      Object.fromEntries(
        Object.entries(dynamicMeshLookup).filter(([key]) =>
          extractKeyPhrases(components.population).includes(key)
        )
      )
    ) : []),
  ];
  const populationTextWords = extractTextWords(components.population, populationMesh);
  const populationBlock: QueryBlock = {
    concept: "P",
    label: "Population",
    meshTerms: Array.from(new Set(populationMesh)),
    textWords: populationTextWords,
    combined: buildBlockQuery(Array.from(new Set(populationMesh)), populationTextWords),
  };
  queryBlocks.push(populationBlock);

  // Concept block
  const conceptMesh = [
    ...conceptStaticMesh,
    ...(dynamicMeshLookup ? extractMeshLabels(
      Object.fromEntries(
        Object.entries(dynamicMeshLookup).filter(([key]) =>
          extractKeyPhrases(components.concept).includes(key)
        )
      )
    ) : []),
  ];
  const conceptTextWords = extractTextWords(components.concept, conceptMesh);
  const conceptBlock: QueryBlock = {
    concept: "Concept",
    label: "Concept",
    meshTerms: Array.from(new Set(conceptMesh)),
    textWords: conceptTextWords,
    combined: buildBlockQuery(Array.from(new Set(conceptMesh)), conceptTextWords),
  };
  queryBlocks.push(conceptBlock);

  // Context block - enhanced with domain-specific terms
  const contextMesh = [
    ...contextStaticMesh,
    ...(dynamicMeshLookup ? extractMeshLabels(
      Object.fromEntries(
        Object.entries(dynamicMeshLookup).filter(([key]) =>
          extractKeyPhrases(components.context).includes(key)
        )
      )
    ) : []),
    // Add outcome domain MeSH terms to context
    ...(contextAnalysis?.suggestedMeshTerms || []),
  ];
  // Add domain-specific text terms
  const contextTextWords = [
    ...extractTextWords(components.context, contextMesh),
    ...(contextAnalysis?.suggestedTextTerms?.slice(0, 5) || []),
  ];
  const contextBlock: QueryBlock = {
    concept: "Context",
    label: "Context",
    meshTerms: Array.from(new Set(contextMesh)),
    textWords: Array.from(new Set(contextTextWords)),
    combined: buildBlockQuery(
      Array.from(new Set(contextMesh)),
      Array.from(new Set(contextTextWords))
    ),
  };
  queryBlocks.push(contextBlock);

  // 6. Build the professional query
  const validBlocks = queryBlocks.filter((b) => b.combined);
  const professionalQuery = validBlocks.map((b) => b.combined).join(" AND ");
  const formattedQuery = formatQueryForDisplay(professionalQuery);
  const pubmedQuery = professionalQuery;

  // 7. Generate alternative queries
  const alternativeQueries: string[] = [];

  // Simple title/abstract search
  const simpleTerms = [components.population, components.concept, components.context]
    .filter(Boolean)
    .join(" AND ");
  alternativeQueries.push(`(${simpleTerms})[tiab]`);

  // MeSH only search
  if (uniqueMeshTerms.length > 0) {
    alternativeQueries.push(uniqueMeshTerms.map((t) => `"${t}"[MeSH]`).join(" AND "));
  }

  // Context-specific searches based on detected intent
  if (contextAnalysis?.queryIntent.includes("cost_effectiveness")) {
    alternativeQueries.push(
      `${professionalQuery} AND ("Cost-Benefit Analysis"[MeSH] OR "Health Care Costs"[MeSH] OR cost[tiab] OR economic[tiab])`
    );
  }

  if (contextAnalysis?.queryIntent.includes("qualitative")) {
    alternativeQueries.push(
      `${professionalQuery} AND (qualitative research[MeSH] OR qualitative[tiab] OR phenomenolog*[tiab] OR grounded theory[tiab] OR ethnograph*[tiab])`
    );
  }

  // Scoping review filter (standard for PCC)
  alternativeQueries.push(
    `${professionalQuery} AND (scoping review[tiab] OR mapping review[tiab] OR systematic map[tiab])`
  );

  // 8. Build search strategy documentation
  const searchStrategy = `
PCC Search Strategy (Enhanced with Dynamic MeSH Lookup):

P (Population): ${components.population}
C (Concept): ${components.concept}
C (Context): ${components.context}

Context Analysis:
- Query Intent: ${contextAnalysis?.queryIntent.join(", ") || "Not analyzed"}
- Outcome Domains: ${contextAnalysis?.outcomeDomains.join(", ") || "Not analyzed"}
- Reasoning: ${contextAnalysis?.reasoning || "N/A"}

Primary PubMed Query:
${formattedQuery}

MeSH Terms Identified:
${uniqueMeshTerms.length > 0 ? uniqueMeshTerms.join(", ") : "None"}

Dynamic MeSH Lookup Results:
${dynamicMeshLookup
  ? Object.entries(dynamicMeshLookup)
      .map(([term, results]) =>
        results.length > 0
          ? `"${term}" -> ${results.map((r) => r.label).join(", ")}`
          : `"${term}" -> No match`
      )
      .join("\n")
  : "Not performed"
}

Query Blocks:
${queryBlocks.map((b) => `${b.concept} (${b.label}): ${b.combined}`).join("\n")}

Alternative Queries:
${alternativeQueries.map((q, i) => `${i + 1}. ${q}`).join("\n")}

Note: PCC framework is typically used for:
- Scoping reviews
- Qualitative/mixed-methods reviews
- Exploratory questions where outcomes are less defined
`.trim();

  return {
    pubmedQuery,
    professionalQuery,
    formattedQuery,
    meshTerms: uniqueMeshTerms,
    searchStrategy,
    alternativeQueries,
    queryBlocks,
    contextAnalysis,
    dynamicMeshLookup,
  };
}

/**
 * Simple synchronous version for backwards compatibility
 */
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
  async ({ population, concept, context, apiKey, provider, model, enhanced }): Promise<string> => {
    const components: PccQueryInput = {
      population,
      concept,
      context,
    };

    // Use enhanced builder if API key provided or explicitly requested
    if (enhanced || apiKey) {
      const result = await buildPccPubMedQueryEnhanced(components, {
        apiKey: apiKey ?? undefined,
        provider: provider ?? undefined,
        model: model ?? undefined,
        useDynamicMesh: true,
        useContextAnalysis: !!apiKey,
      });

      return JSON.stringify({
        success: true,
        components: { population, concept, context },
        generatedQuery: result.pubmedQuery,
        professionalQuery: result.professionalQuery,
        formattedQuery: result.formattedQuery,
        meshTerms: result.meshTerms,
        searchStrategy: result.searchStrategy,
        alternativeQueries: result.alternativeQueries,
        queryBlocks: result.queryBlocks,
        contextAnalysis: result.contextAnalysis,
        enhanced: true,
      });
    }

    // Fallback to simple builder
    const result = buildPccPubMedQuery(components);

    return JSON.stringify({
      success: true,
      components: { population, concept, context },
      generatedQuery: result.pubmedQuery,
      professionalQuery: result.professionalQuery,
      formattedQuery: result.formattedQuery,
      meshTerms: result.meshTerms,
      searchStrategy: result.searchStrategy,
      alternativeQueries: result.alternativeQueries,
      queryBlocks: result.queryBlocks,
      enhanced: false,
    });
  },
  {
    name: "pcc_query_builder",
    description:
      "Builds an optimized PubMed search query from PCC components (Population, Concept, Context). Used for scoping reviews and qualitative research questions. Automatically maps terms to MeSH headings using both static mappings and dynamic NLM API lookup. When API key is provided, performs semantic context analysis to detect query intent (clinical, economic, safety) and suggests relevant domain-specific MeSH terms.",
    schema: z.object({
      population: z.string().describe("P - Population/Participants"),
      concept: z.string().describe("C - Concept/Phenomenon of interest"),
      context: z.string().describe("C - Context/Setting"),
      apiKey: z.string().optional().nullable().describe("LLM API key for semantic context analysis"),
      provider: z.enum(["openai", "anthropic", "google"]).optional().nullable().describe("LLM provider"),
      model: z.string().optional().nullable().describe("Model name override"),
      enhanced: z.boolean().optional().nullable().describe("Force enhanced mode with dynamic MeSH lookup"),
    }),
  }
);

export { buildPccPubMedQuery, buildPccPubMedQueryEnhanced };
