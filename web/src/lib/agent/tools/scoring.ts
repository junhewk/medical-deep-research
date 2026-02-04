/**
 * Composite scoring algorithm for search results ranking
 *
 * Scoring formula:
 * compositeScore = (evidenceLevel × 0.4) + (citationScore × 0.3) + (recencyScore × 0.3)
 */

export type EvidenceLevel = "Level I" | "Level II" | "Level III" | "Level IV" | "Level V";

export interface ScoredResult {
  id: string;
  title: string;
  url?: string;
  source: string;
  evidenceLevel?: EvidenceLevel;
  citationCount?: number;
  publicationDate?: string;
  // Calculated scores
  evidenceLevelScore: number;
  citationScore: number;
  recencyScore: number;
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
 * Half-life of 5 years - papers 5 years old get 0.5 score
 */
export function getRecencyScore(publicationDate?: string): number {
  if (!publicationDate) return 0.5; // Default for unknown

  const pubDate = new Date(publicationDate);
  const now = new Date();

  if (isNaN(pubDate.getTime())) return 0.5;

  const yearsOld = (now.getTime() - pubDate.getTime()) / (1000 * 60 * 60 * 24 * 365.25);

  // 0.5^(yearsOld / 5) - exponential decay, 5-year half-life
  // Minimum score of 0.1 for very old papers
  const score = Math.pow(0.5, yearsOld / 5);
  return Math.max(score, 0.1);
}

/**
 * Calculate composite score for a single result
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
  source: "pubmed" | "scopus" | "cochrane" | "other";
  evidenceLevel?: EvidenceLevel | string;
  publicationType?: string;
  citationCount?: number;
  meshTerms?: string[];
}

/**
 * Score and sort results from multiple sources
 */
export function scoreAndSortResults(results: UnifiedSearchResult[]): ScoredResult[] {
  // Calculate scores for each result
  const scoredResults: ScoredResult[] = results.map((result) => {
    const scores = calculateCompositeScore(
      result.evidenceLevel,
      result.citationCount,
      result.publicationDate || result.publicationYear
    );

    return {
      id: result.id,
      title: result.title,
      url: result.url,
      source: result.source,
      evidenceLevel: result.evidenceLevel as EvidenceLevel | undefined,
      citationCount: result.citationCount,
      publicationDate: result.publicationDate || result.publicationYear,
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
  return `Evidence: ${Math.round(result.evidenceLevelScore * 100)}% | Citations: ${Math.round(result.citationScore * 100)}% | Recency: ${Math.round(result.recencyScore * 100)}% | Total: ${Math.round(result.compositeScore * 100)}%`;
}
