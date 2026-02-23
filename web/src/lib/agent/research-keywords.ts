/**
 * Shared keyword constants for research domain classification and context analysis.
 * Used by deep-agent.ts (domain classification) and query-context-analyzer.ts (intent detection).
 *
 * Centralizing these prevents keyword lists from drifting out of sync.
 */

export const POLICY_KEYWORDS = [
  "policy",
  "regulation",
  "legislation",
  "governance",
  "health system",
  "workforce",
  "reform",
  "implementation science",
  "health equity",
  "disparit",
];

export const ETHICS_KEYWORDS = [
  "ethic",
  "bioethic",
  "moral",
  "autonomy",
  "consent",
  "justice",
  "beneficence",
  "dignity",
  "human rights",
];

/**
 * Match a keyword against text using word-boundary-aware matching.
 * Uses \b at the start to prevent mid-word false positives
 * (e.g., "moral" won't match "femoral", "mg" won't match mid-word).
 * No \b at the end to allow stem matching
 * (e.g., "ethic" matches "ethics", "ethical").
 */
export function matchesKeyword(text: string, keyword: string): boolean {
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`\\b${escaped}`, "i").test(text);
}
