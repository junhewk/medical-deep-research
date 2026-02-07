// Search engine tools
export {
  pubmedSearchTool,
  searchPubMed,
  fetchPubMedDetails,
  comprehensivePubMedSearch,
  isLandmarkJournal,
  type PubMedArticle,
  type SearchStrategy,
  type DateRange,
} from "./pubmed";
export {
  scopusSearchTool,
  searchScopus,
  convertToScopusQuery,
  buildScopusQueryFromPICO,
  type ScopusArticle,
  type ScopusSortBy,
} from "./scopus";
export { cochraneSearchTool, searchCochrane, type CochraneReview } from "./cochrane";
export {
  openalexSearchTool,
  searchOpenAlex,
  reconstructAbstract,
  type OpenAlexArticle,
} from "./openalex";
export {
  semanticScholarSearchTool,
  searchSemanticScholar,
  type SemanticScholarArticle,
} from "./semantic-scholar";

// Query builder tools
export {
  picoQueryBuilderTool,
  buildPubMedQuery,
  buildPubMedQueryEnhanced,
  parsePopulationCriteria,
  generateExclusionKeywords,
  type PicoQueryInput,
  type GeneratedPicoQuery,
  type ParsedPopulationCriteria,
  type EnhancedPicoQueryOptions,
} from "./pico-query";
export {
  pccQueryBuilderTool,
  buildPccPubMedQuery,
  buildPccPubMedQueryEnhanced,
  type PccQueryInput,
  type GeneratedPccQuery,
  type EnhancedPccQueryOptions,
} from "./pcc-query";

// Dynamic MeSH resolver (NLM API integration)
export {
  meshResolverTool,
  lookupMeshTerm,
  batchLookupMeshTerms,
  extractMeshLabels,
  extractKeyPhrases,
  type MeshLookupResult,
} from "./mesh-resolver";

// Shared LLM factory
export {
  createLLM,
  createVerifierLLM,
  DEFAULT_FAST_MODELS,
  type LLMProvider,
  type SupportedLLM,
} from "./llm-factory";

// Query context analyzer (LLM-based semantic analysis)
export {
  queryContextAnalyzerTool,
  analyzeQueryContext,
  detectContextHeuristic,
  createFallbackContextAnalysis,
  getOutcomeDomainMeshTerms,
  getOutcomeDomainTextTerms,
  type QueryIntent,
  type OutcomeDomain,
  type ComparisonStructure,
  type SearchModifiers,
  type QueryContextAnalysis,
} from "./query-context-analyzer";

// Query formatting utilities
export {
  buildBlockQuery,
  buildProfessionalQuery,
  formatQueryForDisplay,
  parseQueryForHighlighting,
  getTokenColorClass,
  extractTextWords,
  type QueryBlock,
  type FormattedQuery,
  type HighlightToken,
} from "./query-formatter";

// Scoring utilities
export {
  calculateCompositeScore,
  calculateContextAwareScore,
  scoreAndSortResults,
  getEvidenceLevelScore,
  getCitationScore,
  getRecencyScore,
  formatScoreBreakdown,
  type EvidenceLevel,
  type ScoringContext,
  type ScoredResult,
  type UnifiedSearchResult,
  type CompositeScore,
  type ContextAwareScoringOptions,
} from "./scoring";

// Population validation tools
export {
  populationValidatorTool,
  validatePopulationWithLLM,
  batchValidatePopulations,
  type TargetCriteria,
  type PopulationValidationResult,
} from "./population-validator";

// Claim verification tools (post-synthesis safety net)
// Uses PubMed as ground truth, not LLM knowledge
export {
  claimVerifierTool,
  verifyReportClaims,
  extractCitationsFromReport,
  verifyPmidInPubMed,
  fetchAbstractFromPubMed,
  type Citation,
  type PmidValidation,
  type VerificationResult,
  type ClaimVerificationReport,
} from "./claim-verifier";

// Utility tools
export {
  meshMappingTool,
  evidenceLevelTool,
  MESH_MAPPINGS,
  EVIDENCE_LEVELS,
} from "./mesh-mapping";

// All tools array for agent setup
import { pubmedSearchTool } from "./pubmed";
import { scopusSearchTool } from "./scopus";
import { cochraneSearchTool } from "./cochrane";
import { picoQueryBuilderTool } from "./pico-query";
import { pccQueryBuilderTool } from "./pcc-query";
import { meshMappingTool, evidenceLevelTool } from "./mesh-mapping";
import { populationValidatorTool } from "./population-validator";
import { claimVerifierTool } from "./claim-verifier";
import { meshResolverTool } from "./mesh-resolver";
import { queryContextAnalyzerTool } from "./query-context-analyzer";
import { openalexSearchTool } from "./openalex";
import { semanticScholarSearchTool } from "./semantic-scholar";

export const allMedicalTools = [
  pubmedSearchTool,
  scopusSearchTool,
  cochraneSearchTool,
  openalexSearchTool,
  semanticScholarSearchTool,
  picoQueryBuilderTool,
  pccQueryBuilderTool,
  meshMappingTool,
  meshResolverTool,
  queryContextAnalyzerTool,
  evidenceLevelTool,
  populationValidatorTool,
  claimVerifierTool,
];

// Re-export middleware tools (dynamically created per research session)
export {
  createWriteTodosTool,
  createFilesystemTools,
  createTaskTool,
  getResearchTodos,
  getSubagentExecutions,
  SUBAGENT_DEFINITIONS,
  type TodoItem,
  type SubagentType,
  type SubagentConfig,
} from "../middleware";
