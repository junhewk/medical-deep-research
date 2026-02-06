import { db } from "@/db";
import { research, agentStates, reports, picoQueries, pccQueries, searchResults, researchTodos, subagentExecutions } from "@/db/schema";
import { eq, desc, asc } from "drizzle-orm";
import { NextResponse } from "next/server";
import { readResearchState, readFinalReport } from "@/lib/state-export";
import { safeJsonParse } from "@/lib/utils";

// GET /api/research/[id] - Get research details and progress
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    // Get research record
    const researchRecord = await db.query.research.findFirst({
      where: eq(research.id, id),
    });

    if (!researchRecord) {
      return NextResponse.json({ error: "Research not found" }, { status: 404 });
    }

    // Get latest agent state
    const latestState = await db.query.agentStates.findFirst({
      where: eq(agentStates.researchId, id),
      orderBy: [desc(agentStates.createdAt)],
    });

    // Get PICO/PCC query if exists
    const picoQuery = await db.query.picoQueries.findFirst({
      where: eq(picoQueries.researchId, id),
    });

    const pccQuery = await db.query.pccQueries.findFirst({
      where: eq(pccQueries.researchId, id),
    });

    // Get report if completed
    let report = null;
    if (researchRecord.status === "completed") {
      report = await db.query.reports.findFirst({
        where: eq(reports.researchId, id),
        orderBy: [desc(reports.createdAt)],
      });
    }

    // Get search results count
    const searchResultsData = await db.query.searchResults.findMany({
      where: eq(searchResults.researchId, id),
    });

    // Get todos (dynamic task tracking)
    const todos = await db.query.researchTodos.findMany({
      where: eq(researchTodos.researchId, id),
      orderBy: [asc(researchTodos.order)],
    });

    // Get subagent executions
    const subagentHistory = await db.query.subagentExecutions.findMany({
      where: eq(subagentExecutions.researchId, id),
      orderBy: [desc(subagentExecutions.createdAt)],
    });

    // Read state markdown file
    const stateMarkdown = await readResearchState(id);
    const reportMarkdown = await readFinalReport(id);

    return NextResponse.json({
      id: researchRecord.id,
      query: researchRecord.query,
      queryType: researchRecord.queryType,
      mode: researchRecord.mode,
      status: researchRecord.status,
      progress: researchRecord.progress,
      title: researchRecord.title,
      createdAt: researchRecord.createdAt,
      startedAt: researchRecord.startedAt,
      completedAt: researchRecord.completedAt,
      durationSeconds: researchRecord.durationSeconds,
      errorMessage: researchRecord.errorMessage,
      phase: latestState?.phase || "init",
      planning_steps: safeJsonParse(latestState?.planningSteps, []),
      active_agents: safeJsonParse(latestState?.activeAgents, []),
      tool_executions: safeJsonParse(latestState?.toolExecutions, []),
      picoQuery: picoQuery
        ? {
            population: picoQuery.population,
            intervention: picoQuery.intervention,
            comparison: picoQuery.comparison,
            outcome: picoQuery.outcome,
            generatedPubmedQuery: picoQuery.generatedPubmedQuery,
            meshTerms: safeJsonParse(picoQuery.meshTerms, []),
          }
        : null,
      pccQuery: pccQuery
        ? {
            population: pccQuery.population,
            concept: pccQuery.concept,
            context: pccQuery.context,
            generatedQuery: pccQuery.generatedQuery,
          }
        : null,
      searchResultsCount: searchResultsData.length,
      report: report
        ? {
            id: report.id,
            title: report.title,
            content: report.content,
            originalContent: report.originalContent,
            language: report.language,
            wordCount: report.wordCount,
            referenceCount: report.referenceCount,
            createdAt: report.createdAt,
          }
        : null,
      result: report?.content || null,
      // Dynamic todos (DeepAgents-style task tracking)
      todos: todos.map(t => ({
        id: t.id,
        content: t.text,
        status: t.status,
        order: t.order,
        completedAt: t.completedAt,
      })),
      // Subagent execution history
      subagentHistory: subagentHistory.map(s => ({
        id: s.id,
        subagent: s.subagentName,
        task: s.task,
        duration: s.duration,
        createdAt: s.createdAt,
      })),
      stateMarkdown,
      reportMarkdown,
    });
  } catch (error) {
    console.error("Error fetching research:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// DELETE /api/research/[id] - Delete research
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    // Check if research exists
    const researchRecord = await db.query.research.findFirst({
      where: eq(research.id, id),
    });

    if (!researchRecord) {
      return NextResponse.json({ error: "Research not found" }, { status: 404 });
    }

    // Delete research (cascades to related tables)
    await db.delete(research).where(eq(research.id, id));

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error deleting research:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}

// PATCH /api/research/[id] - Cancel research
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const { action } = body;

    if (action === "cancel") {
      await db
        .update(research)
        .set({ status: "cancelled" })
        .where(eq(research.id, id));

      return NextResponse.json({ success: true });
    }

    return NextResponse.json({ error: "Invalid action" }, { status: 400 });
  } catch (error) {
    console.error("Error updating research:", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
