/**
 * Todo Middleware for Medical Deep Research
 *
 * Implements write_todos tool for dynamic task planning during research.
 * Todos are persisted to the database and replace hardcoded planningSteps.
 */

import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import { db } from "@/db";
import { researchTodos } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";

/**
 * Todo item schema matching DeepAgents convention
 */
const TodoItemSchema = z.object({
  content: z.string().describe("The todo item text"),
  status: z.enum(["pending", "in_progress", "completed"]).describe("Status of the todo"),
});

export type TodoItem = z.infer<typeof TodoItemSchema>;

/**
 * Input schema for write_todos tool
 */
const WriteTodosInputSchema = z.object({
  todos: z.array(TodoItemSchema).describe("Array of todo items with content and status"),
});

/**
 * Create a write_todos tool that persists todos to the database
 *
 * @param researchId - The research session ID to associate todos with
 * @returns DynamicStructuredTool for writing todos
 */
export function createWriteTodosTool(researchId: string): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "write_todos",
    description: `Create or update the task list for this research session. Use this to track progress through the research workflow.

Common research workflow tasks:
1. Analyze research question
2. Build search query (PICO/PCC)
3. Search databases (PubMed, Scopus, Cochrane)
4. Evaluate and score results
5. Synthesize findings
6. Verify claims (optional)
7. Generate final report

Update todo status as you progress:
- "pending" - Not yet started
- "in_progress" - Currently working on
- "completed" - Finished`,
    schema: WriteTodosInputSchema,
    func: async ({ todos }: { todos: TodoItem[] }) => {
      try {
        // Delete existing todos for this research
        await db.delete(researchTodos).where(eq(researchTodos.researchId, researchId));

        // Insert new todos
        const now = new Date();
        for (let i = 0; i < todos.length; i++) {
          const todo = todos[i];
          await db.insert(researchTodos).values({
            id: generateId(),
            researchId,
            text: todo.content,
            status: todo.status,
            order: i,
            createdAt: now,
            completedAt: todo.status === "completed" ? now : null,
          });
        }

        // Return summary
        const pending = todos.filter(t => t.status === "pending").length;
        const inProgress = todos.filter(t => t.status === "in_progress").length;
        const completed = todos.filter(t => t.status === "completed").length;

        return JSON.stringify({
          success: true,
          message: `Updated ${todos.length} todos: ${completed} completed, ${inProgress} in progress, ${pending} pending`,
          todos: todos.map((t, i) => ({ order: i, ...t })),
        });
      } catch (error) {
        return JSON.stringify({
          success: false,
          error: error instanceof Error ? error.message : "Failed to write todos",
        });
      }
    },
  });
}

/**
 * Get todos for a research session
 *
 * @param researchId - The research session ID
 * @returns Array of todo items ordered by position
 */
export async function getResearchTodos(researchId: string): Promise<TodoItem[]> {
  const todos = await db.query.researchTodos.findMany({
    where: eq(researchTodos.researchId, researchId),
    orderBy: (todos, { asc }) => [asc(todos.order)],
  });

  return todos.map(t => ({
    content: t.text,
    status: t.status as "pending" | "in_progress" | "completed",
  }));
}

/**
 * Update a single todo's status
 *
 * @param todoId - The todo ID
 * @param status - New status
 */
export async function updateTodoStatus(
  todoId: string,
  status: "pending" | "in_progress" | "completed"
): Promise<void> {
  await db
    .update(researchTodos)
    .set({
      status,
      completedAt: status === "completed" ? new Date() : null,
    })
    .where(eq(researchTodos.id, todoId));
}
