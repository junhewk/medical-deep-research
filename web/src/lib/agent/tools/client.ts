/**
 * Client-safe exports from tools module
 *
 * These exports do NOT include any server-side dependencies (database, better-sqlite3)
 * and can be safely imported in client-side React components.
 */

// Query formatting utilities (pure functions, no server deps)
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

// Types from query builders (just type definitions)
export type { PicoQueryInput, GeneratedPicoQuery, ParsedPopulationCriteria } from "./pico-query";
export type { PccQueryInput, GeneratedPccQuery } from "./pcc-query";

// Types from mesh resolver
export type { MeshLookupResult } from "./mesh-resolver";

// Types from context analyzer
export type {
  QueryIntent,
  OutcomeDomain,
  ComparisonStructure,
  SearchModifiers,
  QueryContextAnalysis,
} from "./query-context-analyzer";

// Scoring types
export type {
  EvidenceLevel,
  ScoringContext,
  ScoredResult,
  UnifiedSearchResult,
  CompositeScore,
  ContextAwareScoringOptions,
} from "./scoring";

// Constants from mesh-mapping (pure data, no server deps)
export { MESH_MAPPINGS, EVIDENCE_LEVELS } from "./mesh-mapping";
