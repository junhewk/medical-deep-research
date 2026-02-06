/**
 * Subagent Middleware for Medical Deep Research
 *
 * Implements task tool for subagent delegation with specialized agents:
 * - database_search: Focused database querying (PubMed, Scopus, Cochrane)
 * - report_synthesis: Evidence synthesis and report generation
 * - claim_verification: Post-synthesis verification
 */

import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import { db } from "@/db";
import { subagentExecutions } from "@/db/schema";
import { generateId } from "@/lib/utils";
import { HumanMessage, SystemMessage, ToolMessage, type BaseMessage } from "@langchain/core/messages";
import { createLLM, type LLMProvider } from "../tools/llm-factory";

/**
 * Subagent definitions with their specialized capabilities
 */
export const SUBAGENT_DEFINITIONS = {
  database_search: {
    name: "database_search",
    description: "Specialized agent for searching medical databases. Has access to PubMed, Scopus, Cochrane, and MeSH resolver tools.",
    systemPrompt: `You are a specialized database search agent for medical research.

Your capabilities:
1. Search PubMed with comprehensive strategies (recent RCTs + systematic reviews + relevance)
2. Search Scopus for citation counts and broader coverage
3. Search Cochrane Library for systematic reviews
4. Use MeSH resolver to find proper medical terminology

When searching:
- Always use multiple databases for comprehensive coverage
- Use "comprehensive" search strategy for clinical questions
- Pay attention to population criteria (LVEF thresholds, age ranges, etc.)
- Return structured results with PMID, DOI, citation counts

Return your findings in JSON format with articles array.`,
    tools: ["pubmed_search", "scopus_search", "cochrane_search", "mesh_resolver"],
  },
  report_synthesis: {
    name: "report_synthesis",
    description: "Specialized agent for synthesizing evidence and generating reports. Has access to evidence level classification and population validation tools.",
    systemPrompt: `You are a specialized report synthesis agent for medical research.

Your capabilities:
1. Classify evidence levels (Level I-V)
2. Validate population matches against target criteria
3. Synthesize findings into comprehensive evidence-based reports

When synthesizing:
- ONLY cite sources you have access to
- ACCURATELY represent study findings, even negative/null results
- Organize by evidence level
- Highlight recent landmark trials
- Use Vancouver citation format

Report structure:
1. Executive Summary
2. Background
3. Methods (search strategy)
4. Results (by evidence level)
5. Discussion
6. Conclusions
7. References`,
    tools: ["evidence_level", "population_validator"],
  },
  claim_verification: {
    name: "claim_verification",
    description: "Specialized agent for verifying claims against PubMed ground truth. Catches hallucinations and directional errors.",
    systemPrompt: `You are a specialized claim verification agent.

Your capabilities:
1. Verify PMIDs exist in PubMed
2. Fetch actual abstracts
3. Compare claims against abstract text
4. Flag directional mismatches

When verifying:
- Check that each cited PMID exists
- Compare stated conclusions against actual abstract text
- Flag any reversal of findings (e.g., "benefit" vs "no benefit")
- Document verification results

This is critical for preventing hallucination in medical literature synthesis.`,
    tools: ["claim_verifier"],
  },
} as const;

export type SubagentType = keyof typeof SUBAGENT_DEFINITIONS;

/**
 * Configuration for subagent execution
 */
export interface SubagentConfig {
  researchId: string;
  apiKey: string;
  provider: LLMProvider;
  model: string;
  ncbiApiKey?: string;
  scopusApiKey?: string;
}


/**
 * Execute a subagent task
 */
async function executeSubagent(
  subagentType: SubagentType,
  task: string,
  config: SubagentConfig,
  toolMap: Map<string, DynamicStructuredTool>
): Promise<{ success: boolean; result: string; duration: number }> {
  const startTime = Date.now();
  const definition = SUBAGENT_DEFINITIONS[subagentType];

  try {
    // Create LLM for subagent (temperature 0.2 for balanced output)
    const llm = createLLM(config.provider, config.apiKey, config.model, 0.2);

    // Get tools for this subagent
    const subagentTools = definition.tools
      .map(name => toolMap.get(name))
      .filter((t): t is DynamicStructuredTool => t !== undefined);

    // Bind tools if available
    const llmWithTools = subagentTools.length > 0 ? llm.bindTools(subagentTools) : llm;

    // Execute subagent conversation
    const messages: BaseMessage[] = [
      new SystemMessage(definition.systemPrompt),
      new HumanMessage(task),
    ];

    let response = await llmWithTools.invoke(messages);
    let iterations = 0;
    const maxIterations = 5;

    // Tool call loop
    while (
      "tool_calls" in response &&
      Array.isArray(response.tool_calls) &&
      response.tool_calls.length > 0 &&
      iterations < maxIterations
    ) {
      iterations++;
      const toolCalls = response.tool_calls;

      // Execute tool calls
      const toolResults: { tool_call_id: string; content: string }[] = [];
      for (const tc of toolCalls) {
        const toolCallId = tc.id || `tool_${Date.now()}`;
        const tool = toolMap.get(tc.name);
        if (tool) {
          // Inject API keys
          const args = { ...tc.args };
          if (tc.name === "pubmed_search" && config.ncbiApiKey) {
            args.apiKey = config.ncbiApiKey;
          }
          if (tc.name === "scopus_search" && config.scopusApiKey) {
            args.apiKey = config.scopusApiKey;
          }
          if (["population_validator", "claim_verifier"].includes(tc.name)) {
            args.apiKey = config.apiKey;
            args.provider = config.provider;
            args.model = config.model;
          }
          if (tc.name === "claim_verifier" && config.ncbiApiKey) {
            args.ncbiApiKey = config.ncbiApiKey;
          }

          try {
            const result = await tool.invoke(args);
            toolResults.push({
              tool_call_id: toolCallId,
              content: result,
            });
          } catch (error) {
            toolResults.push({
              tool_call_id: toolCallId,
              content: JSON.stringify({ error: error instanceof Error ? error.message : "Tool error" }),
            });
          }
        }
      }

      // Add tool responses to messages
      messages.push(response);
      for (const result of toolResults) {
        messages.push(new ToolMessage({
          tool_call_id: result.tool_call_id,
          content: result.content,
        }));
      }

      // Get next response
      response = await llmWithTools.invoke(messages);
    }

    const duration = Date.now() - startTime;
    const result = typeof response.content === "string"
      ? response.content
      : JSON.stringify(response.content);

    // Record execution
    await db.insert(subagentExecutions).values({
      id: generateId(),
      researchId: config.researchId,
      subagentName: subagentType,
      task,
      result: result.substring(0, 50000), // Limit stored result
      duration,
      createdAt: new Date(),
    });

    return { success: true, result, duration };
  } catch (error) {
    const duration = Date.now() - startTime;
    const errorMsg = error instanceof Error ? error.message : "Subagent execution failed";

    // Record failed execution
    await db.insert(subagentExecutions).values({
      id: generateId(),
      researchId: config.researchId,
      subagentName: subagentType,
      task,
      result: `ERROR: ${errorMsg}`,
      duration,
      createdAt: new Date(),
    });

    return { success: false, result: errorMsg, duration };
  }
}

/**
 * Create task tool for subagent delegation
 */
export function createTaskTool(
  config: SubagentConfig,
  toolMap: Map<string, DynamicStructuredTool>
): DynamicStructuredTool {
  const subagentNames = Object.keys(SUBAGENT_DEFINITIONS);
  const subagentDescriptions = Object.entries(SUBAGENT_DEFINITIONS)
    .map(([name, def]) => `- ${name}: ${def.description}`)
    .join("\n");

  return new DynamicStructuredTool({
    name: "task",
    description: `Delegate a task to a specialized subagent.

Available subagents:
${subagentDescriptions}

Use subagents for:
- database_search: When you need comprehensive database searches
- report_synthesis: When synthesizing findings into a report
- claim_verification: After synthesis to verify accuracy

Subagents run with isolated context and return results.`,
    schema: z.object({
      subagent: z.enum(subagentNames as [string, ...string[]]).describe("The subagent to delegate to"),
      task: z.string().describe("Detailed task description for the subagent"),
    }),
    func: async ({ subagent, task }: { subagent: string; task: string }) => {
      if (!subagentNames.includes(subagent)) {
        return JSON.stringify({
          success: false,
          error: `Unknown subagent: ${subagent}. Available: ${subagentNames.join(", ")}`,
        });
      }

      const result = await executeSubagent(
        subagent as SubagentType,
        task,
        config,
        toolMap
      );

      return JSON.stringify({
        success: result.success,
        subagent,
        duration_ms: result.duration,
        result: result.result,
      });
    },
  });
}

/**
 * Get subagent execution history for a research session
 */
export async function getSubagentExecutions(researchId: string) {
  return db.query.subagentExecutions.findMany({
    where: (executions, { eq }) => eq(executions.researchId, researchId),
    orderBy: (executions, { desc }) => [desc(executions.createdAt)],
  });
}
