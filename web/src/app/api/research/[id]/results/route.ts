import { db } from "@/db";
import { searchResults } from "@/db/schema";
import { eq, desc } from "drizzle-orm";
import { NextResponse } from "next/server";
import { formatVancouverCitation, type CitationData } from "@/lib/citation/vancouver";
import { calculateCompositeScore, type EvidenceLevel } from "@/lib/agent/tools/scoring";
import { safeJsonParse } from "@/lib/utils";

interface RouteParams {
  params: Promise<{ id: string }>;
}

// GET /api/research/[id]/results - Get search results with scores
export async function GET(request: Request, { params }: RouteParams) {
  try {
    const { id } = await params;

    const results = await db.query.searchResults.findMany({
      where: eq(searchResults.researchId, id),
      orderBy: [desc(searchResults.compositeScore)],
    });

    // Format results with citations
    const formattedResults = results.map((result, index) => {
      const authors = safeJsonParse<string[]>(result.authors, []);

      // Calculate scores if not already present
      let scores = {
        compositeScore: result.compositeScore,
        evidenceLevelScore: result.evidenceLevelScore,
        citationScore: result.citationScore,
        recencyScore: result.recencyScore,
      };

      if (scores.compositeScore === null) {
        scores = calculateCompositeScore(
          result.evidenceLevel as EvidenceLevel | undefined,
          result.citationCount ?? undefined,
          result.publicationYear ?? undefined
        );
      }

      // Generate Vancouver citation if not present
      let vancouverCitation = result.vancouverCitation;
      if (!vancouverCitation && result.title) {
        const citationData: CitationData = {
          id: result.id,
          title: result.title,
          authors,
          journal: result.journal ?? undefined,
          volume: result.volume ?? undefined,
          issue: result.issue ?? undefined,
          pages: result.pages ?? undefined,
          publicationYear: result.publicationYear ?? undefined,
          doi: result.doi ?? undefined,
          pmid: result.pmid ?? undefined,
        };
        vancouverCitation = formatVancouverCitation(citationData);
      }

      return {
        id: result.id,
        referenceNumber: result.referenceNumber ?? index + 1,
        title: result.title,
        authors,
        journal: result.journal,
        volume: result.volume,
        issue: result.issue,
        pages: result.pages,
        publicationYear: result.publicationYear,
        doi: result.doi,
        pmid: result.pmid,
        url: result.url,
        source: result.source,
        evidenceLevel: result.evidenceLevel,
        citationCount: result.citationCount,
        // Scores
        compositeScore: scores.compositeScore,
        evidenceLevelScore: scores.evidenceLevelScore,
        citationScore: scores.citationScore,
        recencyScore: scores.recencyScore,
        // Citation
        vancouverCitation,
        // Metadata
        snippet: result.snippet,
        meshTerms: safeJsonParse<string[]>(result.meshTerms, []),
        createdAt: result.createdAt,
      };
    });

    // Generate reference list
    const referenceList = formattedResults
      .map((r) => `${r.referenceNumber}. ${r.vancouverCitation}`)
      .join("\n");

    return NextResponse.json({
      count: formattedResults.length,
      results: formattedResults,
      referenceList,
    });
  } catch (error) {
    console.error("Error fetching search results:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
