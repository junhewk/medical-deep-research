/**
 * Vancouver-style citation formatter
 *
 * Vancouver format example:
 * Smith AB, Jones CD. Title of article. Journal Name. 2024;45(3):123-130. doi:10.1000/example
 */

export interface CitationData {
  id: string;
  title: string;
  authors?: string[];
  journal?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publicationYear?: string;
  doi?: string;
  pmid?: string;
  url?: string;
}

/**
 * Format author list for Vancouver citation
 * - Max 6 authors, then "et al."
 * - Format: "LastName AB, LastName CD, ..."
 */
export function formatAuthors(authors?: string[]): string {
  if (!authors || authors.length === 0) {
    return "[No authors listed]";
  }

  // If authors already in correct format, use them
  if (authors.length <= 6) {
    return authors.join(", ");
  }

  // More than 6 authors: show first 6 + et al.
  return authors.slice(0, 6).join(", ") + ", et al.";
}

/**
 * Parse and reformat author name to Vancouver style
 * Input formats:
 * - "John Smith" -> "Smith J"
 * - "Smith, John" -> "Smith J"
 * - "John A. Smith" -> "Smith JA"
 */
export function formatAuthorName(name: string): string {
  if (!name) return "";

  // Already in "LastName AB" format?
  if (/^[A-Z][a-z]+\s[A-Z]{1,3}$/.test(name)) {
    return name;
  }

  // Handle "LastName, FirstName MiddleName" format
  if (name.includes(",")) {
    const [lastName, rest] = name.split(",").map((s) => s.trim());
    if (rest) {
      const initials = rest
        .split(/\s+/)
        .map((n) => n.charAt(0).toUpperCase())
        .join("");
      return `${lastName} ${initials}`;
    }
    return lastName;
  }

  // Handle "FirstName MiddleName LastName" format
  const parts = name.split(/\s+/);
  if (parts.length >= 2) {
    const lastName = parts[parts.length - 1];
    const initials = parts
      .slice(0, -1)
      .map((n) => n.charAt(0).toUpperCase())
      .join("");
    return `${lastName} ${initials}`;
  }

  return name;
}

/**
 * Format a single Vancouver-style citation
 *
 * Format: Authors. Title. Journal. Year;Volume(Issue):Pages. doi:DOI
 */
export function formatVancouverCitation(data: CitationData): string {
  const parts: string[] = [];

  // Authors
  if (data.authors && data.authors.length > 0) {
    const formattedAuthors = data.authors.map(formatAuthorName);
    parts.push(formatAuthors(formattedAuthors));
  }

  // Title (ensure period at end)
  if (data.title) {
    const title = data.title.endsWith(".") ? data.title : data.title + ".";
    parts.push(title);
  }

  // Journal
  if (data.journal) {
    let journalPart = data.journal;

    // Add year, volume, issue, pages
    if (data.publicationYear) {
      journalPart += `. ${data.publicationYear}`;

      if (data.volume) {
        journalPart += `;${data.volume}`;

        if (data.issue) {
          journalPart += `(${data.issue})`;
        }

        if (data.pages) {
          journalPart += `:${data.pages}`;
        }
      }
    }

    journalPart += ".";
    parts.push(journalPart);
  } else if (data.publicationYear) {
    // No journal but have year
    parts.push(`${data.publicationYear}.`);
  }

  // DOI
  if (data.doi) {
    const doiClean = data.doi.replace(/^https?:\/\/doi\.org\//, "");
    parts.push(`doi:${doiClean}`);
  }

  // PMID (if no DOI)
  if (!data.doi && data.pmid) {
    parts.push(`PMID: ${data.pmid}`);
  }

  return parts.join(" ");
}

/**
 * Generate numbered reference list in Vancouver format
 */
export function generateReferenceList(citations: CitationData[]): string {
  if (citations.length === 0) {
    return "No references.";
  }

  return citations
    .map((citation, index) => {
      const number = index + 1;
      const formatted = formatVancouverCitation(citation);
      return `${number}. ${formatted}`;
    })
    .join("\n");
}

/**
 * Create a map from identifiers (PMID, DOI) to reference numbers
 */
export function createReferenceMap(citations: CitationData[]): Map<string, number> {
  const map = new Map<string, number>();

  citations.forEach((citation, index) => {
    const refNum = index + 1;

    if (citation.pmid) {
      map.set(citation.pmid, refNum);
      map.set(`PMID:${citation.pmid}`, refNum);
      map.set(`PMID: ${citation.pmid}`, refNum);
    }

    if (citation.doi) {
      const doiClean = citation.doi.replace(/^https?:\/\/doi\.org\//, "");
      map.set(citation.doi, refNum);
      map.set(doiClean, refNum);
      map.set(`doi:${doiClean}`, refNum);
      map.set(`DOI:${doiClean}`, refNum);
    }

    // Also map by title (lowercased for matching)
    if (citation.title) {
      map.set(citation.title.toLowerCase(), refNum);
    }
  });

  return map;
}

/**
 * Replace PMID/DOI in text with [n] in-text citations
 */
export function replaceWithInTextCitations(
  text: string,
  referenceMap: Map<string, number>
): string {
  let result = text;

  // Replace PMID mentions
  result = result.replace(
    /PMID:\s*(\d+)/gi,
    (match, pmid) => {
      const refNum = referenceMap.get(pmid) || referenceMap.get(`PMID:${pmid}`);
      return refNum ? `[${refNum}]` : match;
    }
  );

  // Replace DOI mentions
  result = result.replace(
    /(?:doi:|https?:\/\/doi\.org\/)([^\s]+)/gi,
    (match, doi) => {
      const refNum = referenceMap.get(doi) || referenceMap.get(`doi:${doi}`);
      return refNum ? `[${refNum}]` : match;
    }
  );

  return result;
}

/**
 * Format citation for inline display (shorter format)
 */
export function formatInlineCitation(data: CitationData): string {
  const parts: string[] = [];

  // First author
  if (data.authors && data.authors.length > 0) {
    const firstAuthor = formatAuthorName(data.authors[0]);
    if (data.authors.length > 1) {
      parts.push(`${firstAuthor} et al.`);
    } else {
      parts.push(firstAuthor);
    }
  }

  // Year
  if (data.publicationYear) {
    parts.push(`(${data.publicationYear})`);
  }

  return parts.join(" ");
}
