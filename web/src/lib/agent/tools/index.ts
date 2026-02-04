// Search engine tools
export { pubmedSearchTool, searchPubMed, fetchPubMedDetails, type PubMedArticle } from "./pubmed";
export { scopusSearchTool, searchScopus, type ScopusArticle } from "./scopus";
export { cochraneSearchTool, searchCochrane, type CochraneReview } from "./cochrane";

// Query builder tools
export {
  picoQueryBuilderTool,
  buildPubMedQuery,
  type PicoComponents,
  type GeneratedQuery,
} from "./pico-query";
export { pccQueryBuilderTool, buildPccPubMedQuery, type PccComponents } from "./pcc-query";

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

export const allMedicalTools = [
  pubmedSearchTool,
  scopusSearchTool,
  cochraneSearchTool,
  picoQueryBuilderTool,
  pccQueryBuilderTool,
  meshMappingTool,
  evidenceLevelTool,
];
