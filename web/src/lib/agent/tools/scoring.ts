/**
 * Composite scoring algorithm for search results ranking
 *
 * Standard scoring formula:
 * compositeScore = (evidenceLevel × 0.4) + (citationScore × 0.3) + (recencyScore × 0.3)
 *
 * Clinical context scoring formula:
 * compositeScore = (evidenceLevel × 0.3) + (citationScore × 0.15) + (recencyScore × 0.4) + (landmarkBonus × 0.08) + (populationMatch × 0.07)
 */

export type EvidenceLevel = "Level I" | "Level II" | "Level III" | "Level IV" | "Level V";

/**
 * Scoring context determines weight distribution
 */
export type ScoringContext = "general" | "clinical";

export interface ScoredResult {
  id: string;
  title: string;
  url?: string;
  source: string;
  evidenceLevel?: EvidenceLevel;
  citationCount?: number;
  publicationDate?: string;
  isLandmarkJournal?: boolean;
  // Calculated scores
  evidenceLevelScore: number;
  citationScore: number;
  recencyScore: number;
  landmarkBonus?: number;
  populationMatchScore?: number;
  compositeScore: number;
  // Reference tracking
  referenceNumber?: number;
}

/**
 * Convert evidence level to numerical score
 * Level I (systematic reviews, meta-analyses) = 1.0
 * Level II (RCTs) = 0.8
 * Level III (non-randomized controlled studies) = 0.6
 * Level IV (case series, cohort studies) = 0.4
 * Level V (expert opinion) = 0.2
 */
export function getEvidenceLevelScore(level?: EvidenceLevel | string): number {
  if (!level) return 0.3; // Default for unknown

  const normalizedLevel = level.toLowerCase().trim();

  // Use regex for precise matching of roman numerals
  if (/\blevel\s*i\b/i.test(normalizedLevel) || /^i$/i.test(normalizedLevel)) {
    return 1.0;
  }
  if (/\blevel\s*ii\b/i.test(normalizedLevel) || /^ii$/i.test(normalizedLevel)) {
    return 0.8;
  }
  if (/\blevel\s*iii\b/i.test(normalizedLevel) || /^iii$/i.test(normalizedLevel)) {
    return 0.6;
  }
  if (/\blevel\s*iv\b/i.test(normalizedLevel) || /^iv$/i.test(normalizedLevel)) {
    return 0.4;
  }
  if (/\blevel\s*v\b/i.test(normalizedLevel) || /^v$/i.test(normalizedLevel)) {
    return 0.2;
  }

  // Fallback: check for publication type indicators
  if (/systematic\s*review|meta.?analysis/i.test(normalizedLevel)) {
    return 1.0;
  }
  if (/randomized|rct/i.test(normalizedLevel)) {
    return 0.8;
  }
  if (/cohort|case.?control/i.test(normalizedLevel)) {
    return 0.6;
  }
  if (/case\s*series|case\s*report/i.test(normalizedLevel)) {
    return 0.4;
  }

  return 0.3; // Default for unknown
}

/**
 * Calculate citation score using logarithmic scale
 * Caps at 1.0 for highly cited papers (1000+ citations)
 */
export function getCitationScore(citationCount?: number): number {
  if (!citationCount || citationCount <= 0) return 0;

  // log(citations + 1) / log(1000), capped at 1.0
  const score = Math.log(citationCount + 1) / Math.log(1000);
  return Math.min(score, 1.0);
}

/**
 * Calculate recency score with exponential decay
 * @param publicationDate - Publication date string
 * @param halfLifeYears - Half-life in years (default: 5, use 3 for clinical context)
 */
export function getRecencyScore(publicationDate?: string, halfLifeYears: number = 5): number {
  if (!publicationDate) return 0.5; // Default for unknown

  const pubDate = new Date(publicationDate);
  const now = new Date();

  if (isNaN(pubDate.getTime())) return 0.5;

  const yearsOld = (now.getTime() - pubDate.getTime()) / (1000 * 60 * 60 * 24 * 365.25);

  // 0.5^(yearsOld / halfLife) - exponential decay
  // Minimum score of 0.1 for very old papers
  const score = Math.pow(0.5, yearsOld / halfLifeYears);
  return Math.max(score, 0.1);
}

/**
 * Calculate composite score for a single result (standard weighting)
 */
export function calculateCompositeScore(
  evidenceLevel?: EvidenceLevel | string,
  citationCount?: number,
  publicationDate?: string
): { evidenceLevelScore: number; citationScore: number; recencyScore: number; compositeScore: number } {
  const evidenceLevelScore = getEvidenceLevelScore(evidenceLevel);
  const citationScore = getCitationScore(citationCount);
  const recencyScore = getRecencyScore(publicationDate);

  // Weighted composite: evidence (40%) + citations (30%) + recency (30%)
  const compositeScore =
    (evidenceLevelScore * 0.4) +
    (citationScore * 0.3) +
    (recencyScore * 0.3);

  return {
    evidenceLevelScore: Math.round(evidenceLevelScore * 100) / 100,
    citationScore: Math.round(citationScore * 100) / 100,
    recencyScore: Math.round(recencyScore * 100) / 100,
    compositeScore: Math.round(compositeScore * 100) / 100,
  };
}

/**
 * Context-aware scoring options
 */
export interface ContextAwareScoringOptions {
  context?: ScoringContext;
  isLandmarkJournal?: boolean;
  populationMatchScore?: number; // 0.0 - 1.0 from AI validator
}

/**
 * Extended composite score result for clinical context
 */
export interface CompositeScore {
  evidenceLevelScore: number;
  citationScore: number;
  recencyScore: number;
  landmarkBonus: number;
  populationMatchScore: number;
  compositeScore: number;
}

/**
 * Calculate context-aware composite score
 *
 * Clinical context uses different weights to prioritize:
 * - Recency (40%): Recent studies more important for clinical decisions
 * - Evidence (30%): Still important but reduced from 40%
 * - Citations (15%): Reduced to prevent old highly-cited papers from dominating
 * - Landmark Journal (8%): Bonus for NEJM, Lancet, JAMA, etc.
 * - Population Match (7%): AI-validated population match score
 *
 * General context uses standard weights (40/30/30)
 */
export function calculateContextAwareScore(
  evidenceLevel?: EvidenceLevel | string,
  citationCount?: number,
  publicationDate?: string,
  options?: ContextAwareScoringOptions
): CompositeScore {
  const context = options?.context || "general";
  const isLandmark = options?.isLandmarkJournal || false;
  const populationMatch = options?.populationMatchScore ?? 1.0; // Default to 1.0 (full match)

  // Calculate base scores
  const evidenceLevelScore = getEvidenceLevelScore(evidenceLevel);
  const citationScore = getCitationScore(citationCount);

  // Use different half-life based on context
  // Clinical: 3-year half-life (more aggressive decay for older papers)
  // General: 5-year half-life (standard)
  const halfLifeYears = context === "clinical" ? 3 : 5;
  const recencyScore = getRecencyScore(publicationDate, halfLifeYears);

  // Landmark journal bonus (0 or 1)
  const landmarkBonus = isLandmark ? 1.0 : 0.0;

  let compositeScore: number;

  if (context === "clinical") {
    // Clinical context weights
    // Evidence: 30%, Citations: 15%, Recency: 40%, Landmark: 8%, Population: 7%
    compositeScore =
      (evidenceLevelScore * 0.30) +
      (citationScore * 0.15) +
      (recencyScore * 0.40) +
      (landmarkBonus * 0.08) +
      (populationMatch * 0.07);
  } else {
    // General context weights (standard)
    // Evidence: 40%, Citations: 30%, Recency: 30%
    compositeScore =
      (evidenceLevelScore * 0.40) +
      (citationScore * 0.30) +
      (recencyScore * 0.30);
  }

  return {
    evidenceLevelScore: Math.round(evidenceLevelScore * 100) / 100,
    citationScore: Math.round(citationScore * 100) / 100,
    recencyScore: Math.round(recencyScore * 100) / 100,
    landmarkBonus: Math.round(landmarkBonus * 100) / 100,
    populationMatchScore: Math.round(populationMatch * 100) / 100,
    compositeScore: Math.round(compositeScore * 100) / 100,
  };
}

/**
 * Unified search result format for scoring
 */
export interface UnifiedSearchResult {
  id: string;
  title: string;
  abstract?: string;
  authors?: string[];
  journal?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publicationDate?: string;
  publicationYear?: string;
  doi?: string;
  pmid?: string;
  url?: string;
  source: "pubmed" | "scopus" | "cochrane" | "openalex" | "semantic_scholar" | "other";
  evidenceLevel?: EvidenceLevel | string;
  publicationType?: string;
  citationCount?: number;
  meshTerms?: string[];
  isLandmarkJournal?: boolean;
  populationMatchScore?: number; // From AI validator (0.0 - 1.0)
}

/**
 * Score and sort results from multiple sources
 * @param results - Array of unified search results
 * @param context - Scoring context ('general' or 'clinical')
 */
export function scoreAndSortResults(
  results: UnifiedSearchResult[],
  context: ScoringContext = "general"
): ScoredResult[] {
  // Calculate scores for each result
  const scoredResults: ScoredResult[] = results.map((result) => {
    const publicationDate = result.publicationDate || result.publicationYear;

    // Use context-aware scoring which handles both contexts
    const scores = calculateContextAwareScore(
      result.evidenceLevel,
      result.citationCount,
      publicationDate,
      {
        context,
        isLandmarkJournal: result.isLandmarkJournal,
        populationMatchScore: result.populationMatchScore,
      }
    );

    return {
      id: result.id,
      title: result.title,
      url: result.url,
      source: result.source,
      evidenceLevel: result.evidenceLevel as EvidenceLevel | undefined,
      citationCount: result.citationCount,
      publicationDate,
      isLandmarkJournal: result.isLandmarkJournal,
      ...scores,
    };
  });

  // Sort by composite score (descending)
  scoredResults.sort((a, b) => b.compositeScore - a.compositeScore);

  // Assign reference numbers in sorted order
  scoredResults.forEach((result, index) => {
    result.referenceNumber = index + 1;
  });

  return scoredResults;
}

/**
 * Get score breakdown as a human-readable string
 */
export function formatScoreBreakdown(result: ScoredResult): string {
  let breakdown = `Evidence: ${Math.round(result.evidenceLevelScore * 100)}% | Citations: ${Math.round(result.citationScore * 100)}% | Recency: ${Math.round(result.recencyScore * 100)}%`;

  // Add landmark bonus if present
  if (result.landmarkBonus !== undefined && result.landmarkBonus > 0) {
    breakdown += ` | Landmark: +${Math.round(result.landmarkBonus * 100)}%`;
  }

  // Add population match if present and not 100%
  if (result.populationMatchScore !== undefined && result.populationMatchScore < 1.0) {
    breakdown += ` | Pop.Match: ${Math.round(result.populationMatchScore * 100)}%`;
  }

  breakdown += ` | Total: ${Math.round(result.compositeScore * 100)}%`;

  return breakdown;
}
