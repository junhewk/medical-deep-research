import { validateRequest } from "@/lib/auth";
import { db } from "@/lib/db";
import { research } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { NextResponse } from "next/server";

const PYTHON_API_URL = process.env.PYTHON_API_URL || "http://localhost:8000";

// GET /api/research/[id] - Get research details/progress
export async function GET(
  request: Request,
  { params }: { params: { id: string } }
) {
  try {
    const { user } = await validateRequest();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // Get research from database
    const item = await db.query.research.findFirst({
      where: and(eq(research.id, params.id), eq(research.userId, user.id)),
    });

    if (!item) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    // If research is running, get progress from Python backend
    if (item.status === "running" || item.status === "pending") {
      try {
        const response = await fetch(`${PYTHON_API_URL}/research/${params.id}`);

        if (response.ok) {
          const progress = await response.json();

          // Update database with latest progress
          await db
            .update(research)
            .set({
              progress: progress.progress || item.progress,
              status: progress.status || item.status,
              result: progress.result
                ? JSON.stringify(progress.result)
                : item.result,
              planningSteps: progress.planning_steps
                ? JSON.stringify(progress.planning_steps)
                : item.planningSteps,
              toolExecutions: progress.tool_executions
                ? JSON.stringify(progress.tool_executions)
                : item.toolExecutions,
              completedAt:
                progress.status === "completed" ? new Date() : item.completedAt,
            })
            .where(eq(research.id, params.id));

          // Return combined data
          return NextResponse.json({
            id: item.id,
            query: item.query,
            status: progress.status || item.status,
            progress: progress.progress || item.progress,
            phase: progress.phase,
            planning_steps: progress.planning_steps || [],
            active_agents: progress.active_agents || [],
            tool_executions: progress.tool_executions || [],
            result: progress.result,
            error: progress.error,
            createdAt: item.createdAt,
            completedAt: item.completedAt,
          });
        }
      } catch (fetchError) {
        console.error("Error fetching from Python API:", fetchError);
      }
    }

    // Return data from database
    return NextResponse.json({
      id: item.id,
      query: item.query,
      status: item.status,
      progress: item.progress,
      planning_steps: item.planningSteps
        ? JSON.parse(item.planningSteps)
        : [],
      tool_executions: item.toolExecutions
        ? JSON.parse(item.toolExecutions)
        : [],
      result: item.result ? JSON.parse(item.result) : null,
      createdAt: item.createdAt,
      completedAt: item.completedAt,
    });
  } catch (error) {
    console.error("Error fetching research:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
