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

// Query builder tools
export {
  picoQueryBuilderTool,
  buildPubMedQuery,
  parsePopulationCriteria,
  generateExclusionKeywords,
  type PicoQueryInput,
  type GeneratedPicoQuery,
  type ParsedPopulationCriteria,
} from "./pico-query";
export { pccQueryBuilderTool, buildPccPubMedQuery, type PccQueryInput, type GeneratedPccQuery } from "./pcc-query";

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

export const allMedicalTools = [
  pubmedSearchTool,
  scopusSearchTool,
  cochraneSearchTool,
  picoQueryBuilderTool,
  pccQueryBuilderTool,
  meshMappingTool,
  evidenceLevelTool,
  populationValidatorTool,
  claimVerifierTool,
];
