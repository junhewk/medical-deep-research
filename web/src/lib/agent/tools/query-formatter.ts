/**
 * Professional PubMed query builder and formatter
 *
 * Generates properly formatted queries with explicit field tags:
 * - [MeSH] for MeSH terms
 * - [tiab] for title/abstract
 * - [pt] for publication type
 * - [dp] for date of publication
 */

/**
 * Common English stopwords to filter out from search terms.
 * Shared across extractTextWords and extractSearchTerms.
 */
const STOPWORDS = new Set([
  // Basic articles and pronouns
  "a", "an", "the", "this", "that", "these", "those",
  // Conjunctions and prepositions
  "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from",
  "as", "into", "through", "during",
  // Verbs (common forms)
  "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
  "do", "does", "did", "will", "would", "could", "should", "may", "might",
  "must", "shall", "can",
  // Other common words
  "it", "its", "if", "so", "no", "not", "such", "than", "too", "very",
  "who", "which", "what", "when", "where", "why", "how",
  "all", "each", "every", "both", "few", "more", "most", "other", "some",
  "only", "same",
  // Comparison operators (should be part of structured query, not text search)
  "vs", "vs.", "versus", "compared", "comparing", "between",
  // Medical context stopwords
  "using", "based", "related", "associated", "among", "within", "without",
]);

export interface QueryBlock {
  concept: "P" | "I" | "C" | "O" | "Concept" | "Context";
  label: string;
  meshTerms: string[];
  textWords: string[];
  combined: string;
}

export interface FormattedQuery {
  professionalQuery: string;
  formattedQuery: string;
  queryBlocks: QueryBlock[];
}

/**
 * Build a single block query combining MeSH terms and text words
 */
export function buildBlockQuery(
  meshTerms: string[],
  textWords: string[]
): string {
  const parts: string[] = [];

  // Add MeSH terms
  meshTerms.forEach((term) => {
    parts.push(`"${term}"[MeSH]`);
  });

  // Add text words for title/abstract search
  textWords.forEach((word) => {
    const cleanWord = word.replace(/['"]/g, "").trim();
    if (cleanWord) {
      parts.push(`${cleanWord}[tiab]`);
    }
  });

  if (parts.length === 0) {
    return "";
  }

  if (parts.length === 1) {
    return parts[0];
  }

  return `(${parts.join(" OR ")})`;
}

/**
 * Build professional PubMed query from blocks
 */
export function buildProfessionalQuery(
  blocks: QueryBlock[],
  filters?: {
    publicationTypes?: string[];
    dateRange?: { start?: string; end?: string };
    humans?: boolean;
    english?: boolean;
  }
): FormattedQuery {
  // Build each block's combined query
  const blockQueries = blocks
    .filter((block) => block.meshTerms.length > 0 || block.textWords.length > 0)
    .map((block) => {
      const combined = buildBlockQuery(block.meshTerms, block.textWords);
      return { ...block, combined };
    });

  if (blockQueries.length === 0) {
    return {
      professionalQuery: "",
      formattedQuery: "",
      queryBlocks: [],
    };
  }

  // Combine blocks with AND
  const mainParts = blockQueries.map((b) => b.combined);
  let professionalQuery = mainParts.join(" AND ");

  // Add filters
  const filterParts: string[] = [];

  if (filters?.publicationTypes && filters.publicationTypes.length > 0) {
    const ptFilters = filters.publicationTypes
      .map((pt) => `${pt}[pt]`)
      .join(" OR ");
    filterParts.push(`(${ptFilters})`);
  }

  if (filters?.dateRange) {
    if (filters.dateRange.start && filters.dateRange.end) {
      filterParts.push(`"${filters.dateRange.start}"[dp]:"${filters.dateRange.end}"[dp]`);
    } else if (filters.dateRange.start) {
      filterParts.push(`"${filters.dateRange.start}"[dp]:3000[dp]`);
    }
  }

  if (filters?.humans) {
    filterParts.push(`"humans"[MeSH Terms]`);
  }

  if (filters?.english) {
    filterParts.push(`english[la]`);
  }

  if (filterParts.length > 0) {
    professionalQuery = `(${professionalQuery}) AND ${filterParts.join(" AND ")}`;
  }

  // Format for display with line breaks
  const formattedQuery = formatQueryForDisplay(professionalQuery);

  return {
    professionalQuery,
    formattedQuery,
    queryBlocks: blockQueries,
  };
}

/**
 * Format query for display with line breaks and indentation
 */
export function formatQueryForDisplay(query: string): string {
  // Replace top-level AND with newlines
  const formatted = query;

  // Track parenthesis depth
  let depth = 0;
  let result = "";
  let i = 0;

  while (i < formatted.length) {
    const char = formatted[i];

    if (char === "(") {
      depth++;
      result += char;
    } else if (char === ")") {
      depth--;
      result += char;
    } else if (formatted.slice(i, i + 5) === " AND " && depth === 0) {
      result += "\nAND\n";
      i += 4; // Skip " AND" (loop will add 1)
    } else if (formatted.slice(i, i + 4) === " OR " && depth === 1) {
      // Keep OR on same line but add space
      result += " OR ";
      i += 3;
    } else {
      result += char;
    }

    i++;
  }

  return result;
}

/**
 * Extract text words from input, excluding terms that became MeSH terms.
 * Used by PICO and PCC query builders.
 */
export function extractTextWords(input: string, meshTerms: string[]): string[] {
  // Get words, filtering out stopwords and short terms
  const words = input
    .toLowerCase()
    .split(/[\s,;]+/)
    .filter((w) => w.length > 2 && !STOPWORDS.has(w));

  // Filter out words that are part of MeSH terms
  const meshLower = meshTerms.map((m) => m.toLowerCase());
  const filtered = words.filter((word) => {
    return !meshLower.some((mesh) => mesh.includes(word));
  });

  // Return unique words, plus the original input as a phrase
  const result = [input];
  for (const w of filtered) {
    if (!result.includes(w) && w !== input.toLowerCase()) {
      result.push(w);
    }
  }

  return result.slice(0, 3); // Limit to avoid overly complex queries
}

/**
 * Parse text to extract potential search terms.
 * Removes stopwords and returns unique meaningful terms.
 */
export function extractSearchTerms(text: string): string[] {
  const words = text
    .toLowerCase()
    .replace(/[^\w\s-]/g, " ")
    .split(/\s+/)
    .filter((word) => word.length > 2 && !STOPWORDS.has(word));

  return Array.from(new Set(words));
}

/**
 * Syntax highlight tokens for display
 */
export interface HighlightToken {
  text: string;
  type: "mesh" | "tiab" | "pt" | "dp" | "operator" | "paren" | "text" | "filter";
}

/**
 * Parse query into highlight tokens
 */
export function parseQueryForHighlighting(query: string): HighlightToken[] {
  const tokens: HighlightToken[] = [];
  let remaining = query;

  while (remaining.length > 0) {
    // Match patterns in order of specificity

    // MeSH term: "term"[MeSH] or "term"[MeSH Terms]
    const meshMatch = remaining.match(/^"([^"]+)"\[MeSH(?:\s+Terms)?\]/i);
    if (meshMatch) {
      tokens.push({ text: meshMatch[0], type: "mesh" });
      remaining = remaining.slice(meshMatch[0].length);
      continue;
    }

    // Title/Abstract: term[tiab]
    const tiabMatch = remaining.match(/^([^\s\[\]]+)\[tiab\]/i);
    if (tiabMatch) {
      tokens.push({ text: tiabMatch[0], type: "tiab" });
      remaining = remaining.slice(tiabMatch[0].length);
      continue;
    }

    // Publication type: term[pt]
    const ptMatch = remaining.match(/^([^\[\]]+)\[pt\]/i);
    if (ptMatch) {
      tokens.push({ text: ptMatch[0], type: "pt" });
      remaining = remaining.slice(ptMatch[0].length);
      continue;
    }

    // Date: "date"[dp] or date[dp]
    const dpMatch = remaining.match(/^"?([^"[\]]+)"?\[dp\]/i);
    if (dpMatch) {
      tokens.push({ text: dpMatch[0], type: "dp" });
      remaining = remaining.slice(dpMatch[0].length);
      continue;
    }

    // Language filter: english[la]
    const laMatch = remaining.match(/^([a-z]+)\[la\]/i);
    if (laMatch) {
      tokens.push({ text: laMatch[0], type: "filter" });
      remaining = remaining.slice(laMatch[0].length);
      continue;
    }

    // Operators: AND, OR, NOT
    const opMatch = remaining.match(/^(AND|OR|NOT)(?=\s|$|\n)/i);
    if (opMatch) {
      tokens.push({ text: opMatch[0], type: "operator" });
      remaining = remaining.slice(opMatch[0].length);
      continue;
    }

    // Parentheses
    if (remaining[0] === "(" || remaining[0] === ")") {
      tokens.push({ text: remaining[0], type: "paren" });
      remaining = remaining.slice(1);
      continue;
    }

    // Whitespace and newlines - keep as text
    const wsMatch = remaining.match(/^(\s+)/);
    if (wsMatch) {
      tokens.push({ text: wsMatch[0], type: "text" });
      remaining = remaining.slice(wsMatch[0].length);
      continue;
    }

    // Any other character
    tokens.push({ text: remaining[0], type: "text" });
    remaining = remaining.slice(1);
  }

  return tokens;
}

/**
 * Get CSS class for highlight token type
 */
export function getTokenColorClass(type: HighlightToken["type"]): string {
  switch (type) {
    case "mesh":
      return "text-green-600 dark:text-green-400";
    case "tiab":
      return "text-blue-600 dark:text-blue-400";
    case "pt":
      return "text-purple-600 dark:text-purple-400";
    case "dp":
      return "text-amber-600 dark:text-amber-400";
    case "filter":
      return "text-cyan-600 dark:text-cyan-400";
    case "operator":
      return "text-orange-600 dark:text-orange-400 font-semibold";
    case "paren":
      return "text-gray-500 dark:text-gray-400";
    default:
      return "";
  }
}
