/**
 * Medical Deep Research Agent - DeepAgents Architecture
 *
 * Refactored from hardcoded StateGraph to dynamic DeepAgents-style workflow:
 * - Todo management via write_todos tool
 * - Filesystem tools for context offloading
 * - Subagent delegation for specialized tasks
 *
 * The agent decides its own workflow via todos instead of following
 * a predetermined sequence of nodes.
 */

import { HumanMessage, SystemMessage, AIMessage } from "@langchain/core/messages";
import { createLLM as createBaseLLM } from "./tools/llm-factory";
import { StateGraph, Annotation, START, END } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { DynamicStructuredTool } from "@langchain/core/tools";
import {
  allMedicalTools,
  calculateCompositeScore,
  type EvidenceLevel,
  pubmedSearchTool,
  scopusSearchTool,
  cochraneSearchTool,
  openalexSearchTool,
  semanticScholarSearchTool,
  convertToScopusQuery,
  buildScopusQueryFromPICO,
} from "./tools";
import {
  createWriteTodosTool,
  createFilesystemTools,
  createTaskTool,
  type SubagentConfig,
} from "./middleware";
import { db } from "@/db";
import { research, agentStates, reports, picoQueries, pccQueries, searchResults, researchTodos } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";
import { exportStateToMarkdown } from "../state-export";
import { formatVancouverCitation, type CitationData } from "@/lib/citation/vancouver";
import { translateReport } from "./tools/report-translator";
import type { Locale } from "@/i18n/config";

/**
 * Normalize authors field: convert string to array if needed
 */
function normalizeAuthors(authors: unknown): string[] {
  if (Array.isArray(authors)) {
    return authors;
  }
  if (typeof authors === "string") {
    return authors
      .replace(/ et al\.?$/, "")
      .split(", ")
      .filter((a) => a.trim());
  }
  return [];
}

/**
 * Fast model for each LLM provider
 */
const FAST_MODELS: Record<string, string> = {
  anthropic: "claude-3-5-haiku-20241022",
  google: "gemini-1.5-flash",
  openai: "gpt-4o-mini",
};

// Tool execution tracking
interface ToolExecution {
  tool: string;
  status: "running" | "completed" | "failed";
  query?: string;
  resultCount?: number;
  duration?: number;
  error?: string;
  startTime?: number;
}

// Agent state annotation
const AgentState = Annotation.Root({
  messages: Annotation<(HumanMessage | AIMessage | SystemMessage)[]>({
    reducer: (current, update) => current.concat(update),
    default: () => [],
  }),
  researchId: Annotation<string>(),
  phase: Annotation<string>({
    value: (_, update) => update,
    default: () => "init",
  }),
  progress: Annotation<number>({
    value: (_, update) => update,
    default: () => 0,
  }),
  planningSteps: Annotation<Array<{ id: string; name: string; status: string }>>({
    value: (_, update) => update,
    default: () => [],
  }),
  toolExecutions: Annotation<ToolExecution[]>({
    reducer: (current, update) => {
      const merged = [...current];
      for (const exec of update) {
        const existingIdx = merged.findIndex(
          (e) => e.tool === exec.tool && e.startTime === exec.startTime
        );
        if (existingIdx >= 0) {
          merged[existingIdx] = exec;
        } else {
          merged.push(exec);
        }
      }
      return merged;
    },
    default: () => [],
  }),
  searchResults: Annotation<unknown[]>({
    reducer: (current, update) => current.concat(update),
    default: () => [],
  }),
  synthesizedContent: Annotation<string>({
    value: (_, update) => update,
    default: () => "",
  }),
  language: Annotation<Locale>({
    value: (_, update) => update,
    default: () => "en" as Locale,
  }),
  originalContent: Annotation<string>({
    value: (_, update) => update,
    default: () => "",
  }),
  searchedDatabases: Annotation<Set<string>>({
    reducer: (current, update) => new Set([...Array.from(current), ...Array.from(update)]),
    default: () => new Set<string>(),
  }),
});

type AgentStateType = typeof AgentState.State;

export interface MedicalResearchConfig {
  researchId: string;
  query: string;
  queryType: "pico" | "pcc" | "free";
  llmProvider: "openai" | "anthropic" | "google";
  model: string;
  apiKey: string;
  scopusApiKey?: string;
  ncbiApiKey?: string;
  picoComponents?: {
    population?: string;
    intervention?: string;
    comparison?: string;
    outcome?: string;
  };
  pccComponents?: {
    population?: string;
    concept?: string;
    context?: string;
  };
  language?: Locale;
  onProgress?: (progress: { phase: string; progress: number; message: string }) => void;
}

/**
 * System prompt with DeepAgents-style workflow instructions
 * Now a function to include dynamic API key availability info
 */
function getSystemPrompt(config: { scopusApiKey?: string; ncbiApiKey?: string }): string {
  const scopusAvailable = !!config.scopusApiKey;
  const ncbiAvailable = !!config.ncbiApiKey;

  return `You are a Medical Research Agent specialized in evidence-based medicine and systematic literature review.

## Core Capabilities
1. Build optimized search queries using PICO or PCC frameworks
2. Search medical databases (PubMed, Scopus, Cochrane Library)
3. Map terms to MeSH headings for better search results
4. Classify evidence levels (Level I-V)
5. Validate study populations against target criteria
6. Synthesize findings into comprehensive reports

## Available API Keys
${scopusAvailable ? "- **Scopus API key: AVAILABLE** - USE scopus_search for citation counts and additional coverage" : "- Scopus API key: NOT configured - skip Scopus searches"}
${ncbiAvailable ? "- **NCBI API key: AVAILABLE** - Enhanced PubMed rate limits" : "- NCBI API key: NOT configured - using public PubMed access"}
- **OpenAlex: ALWAYS AVAILABLE** - No API key needed. Use openalex_search for citation counts and broad coverage
- **Semantic Scholar: ALWAYS AVAILABLE** - No API key needed. Use semantic_scholar_search for additional coverage (Medicine-filtered)

## Task Management (write_todos)

Before starting research, use write_todos to create a task list:
1. Analyze research question
2. Build search query (PICO/PCC)
3. Search databases (PubMed${scopusAvailable ? ", Scopus" : ", OpenAlex, Semantic Scholar"}, Cochrane)
4. Evaluate and score results
5. Synthesize findings
6. Verify claims (optional)
7. Generate final report

Update todo status as you progress:
- "pending" - Not yet started
- "in_progress" - Currently working on
- "completed" - Finished

## Context Management (Filesystem)

For large result sets (>20 articles):
- Use write_file to store raw results: write_file("search_results/pubmed.json", JSON.stringify(results))
- Read back with read_file when synthesizing
- Use ls to see what files have been stored

## Subagent Delegation (task)

For complex research, delegate to specialized subagents:
- database_search: Focused database querying (PubMed, Scopus, Cochrane)
- report_synthesis: Evidence synthesis and report generation
- claim_verification: Post-synthesis verification against PubMed ground truth

## Search Strategy Guidelines

### For Clinical Questions (PICO)
**CRITICAL: Use "comprehensive" search strategy** to prioritize recent landmark trials:
- Always set searchStrategy: "comprehensive" when calling pubmed_search
- This ensures recent RCTs (last 3 years) from NEJM, Lancet, JAMA are prioritized

### Population Matching
**CRITICAL: Validate population matches** to avoid evidence misapplication:
- If query specifies LVEF >= 50% (preserved EF), exclude HFrEF studies
- Use the population_validator tool to verify study populations match criteria

### Database Coverage
**ALWAYS search multiple databases** for comprehensive coverage:
- PubMed (comprehensive strategy)
- Cochrane for systematic reviews
${scopusAvailable ? "- **Scopus (API key available)** - USE THIS for citation counts and broader coverage" : "- Scopus: SKIP (no API key configured)\n- **OpenAlex** - USE for citation counts and broad coverage (free, no key needed)\n- **Semantic Scholar** - USE for additional Medicine-filtered coverage (free, no key needed)"}

## Report Format (Markdown)

Structure reports with:
1. Executive Summary (highlight key finding, cite landmark trial)
2. Background
3. Methods (search strategy, databases, population criteria)
4. Results (organized by evidence level, with [n] citations)
5. Discussion (address population-specific considerations)
6. Conclusions
7. References (Vancouver format with PMIDs/DOIs)

## Anti-Hallucination Rules

**CRITICAL:**
- ONLY cite sources from your search results
- ONLY state what abstracts EXPLICITLY say
- If conclusion says "no significant difference", report that
- NEVER reverse or contradict what actual abstracts state

## Post-Synthesis Verification

After synthesizing, use claim_verifier tool to validate:
- Verifies PMIDs exist in PubMed
- Compares claims against actual abstracts
- Flags directional mismatches`;
}

/** Create LLM for agent with temperature 0.3 for balanced creativity */
function createLLM(
  provider: "openai" | "anthropic" | "google",
  model: string,
  apiKey: string
) {
  return createBaseLLM(provider, apiKey, model, 0.3);
}

/**
 * Persist search results to database with composite scoring and Vancouver citations
 */
interface PersistableResult {
  title: string;
  authors?: string[];
  journal?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publicationYear?: string;
  publicationDate?: string;
  doi?: string;
  pmid?: string;
  url?: string;
  abstract?: string;
  source: string;
  evidenceLevel?: string;
  citationCount?: number;
  meshTerms?: string[];
}

async function persistSearchResults(
  researchId: string,
  results: PersistableResult[]
): Promise<void> {
  if (!results || results.length === 0) return;

  const scoredResults = results.map((result) => {
    const scores = calculateCompositeScore(
      result.evidenceLevel as EvidenceLevel | undefined,
      result.citationCount,
      result.publicationDate || result.publicationYear
    );
    return { ...result, ...scores };
  });

  scoredResults.sort((a, b) => b.compositeScore - a.compositeScore);

  for (let i = 0; i < scoredResults.length; i++) {
    const result = scoredResults[i];
    const refNumber = i + 1;

    const citationData: CitationData = {
      id: generateId(),
      title: result.title,
      authors: result.authors,
      journal: result.journal,
      volume: result.volume,
      issue: result.issue,
      pages: result.pages,
      publicationYear: result.publicationYear,
      doi: result.doi,
      pmid: result.pmid,
    };
    const vancouverCitation = formatVancouverCitation(citationData);

    await db.insert(searchResults).values({
      id: generateId(),
      researchId,
      title: result.title,
      url: result.url,
      snippet: result.abstract?.substring(0, 500),
      source: result.source,
      evidenceLevel: result.evidenceLevel,
      doi: result.doi,
      pmid: result.pmid,
      authors: JSON.stringify(result.authors || []),
      journal: result.journal,
      volume: result.volume,
      issue: result.issue,
      pages: result.pages,
      publicationYear: result.publicationYear,
      citationCount: result.citationCount,
      meshTerms: JSON.stringify(result.meshTerms || []),
      compositeScore: result.compositeScore,
      evidenceLevelScore: result.evidenceLevelScore,
      citationScore: result.citationScore,
      recencyScore: result.recencyScore,
      referenceNumber: refNumber,
      vancouverCitation,
      createdAt: new Date(),
    });
  }
}

async function updateProgress(
  researchId: string,
  phase: string,
  progress: number,
  message: string,
  state: Partial<AgentStateType>,
  onProgress?: (progress: { phase: string; progress: number; message: string }) => void
): Promise<void> {
  const stateId = generateId();
  const now = new Date();

  await db
    .update(research)
    .set({
      status: phase === "complete" ? "completed" : "running",
      progress,
    })
    .where(eq(research.id, researchId));

  // Get current todos for planning steps
  const todos = await db.query.researchTodos.findMany({
    where: eq(researchTodos.researchId, researchId),
    orderBy: (todos, { asc }) => [asc(todos.order)],
  });

  const planningSteps = todos.map((t, i) => ({
    id: String(i + 1),
    name: t.text,
    status: t.status === "completed" ? "completed" :
            t.status === "in_progress" ? "in_progress" : "pending",
  }));

  const activeAgents = [];
  if (phase === "planning") {
    activeAgents.push({ name: "Query Builder", status: "active" });
  } else if (phase === "searching") {
    activeAgents.push({ name: "Database Search", status: "active" });
  } else if (phase === "synthesizing") {
    activeAgents.push({ name: "Report Generator", status: "active" });
  } else if (phase === "translating") {
    activeAgents.push({ name: "Report Translator", status: "active" });
  }

  await db.insert(agentStates).values({
    id: stateId,
    researchId,
    phase,
    message,
    overallProgress: progress,
    planningSteps: JSON.stringify(planningSteps),
    activeAgents: JSON.stringify(activeAgents),
    toolExecutions: JSON.stringify(state.toolExecutions || []),
    createdAt: now,
    updatedAt: now,
  });

  await exportStateToMarkdown(researchId, phase, state);

  if (onProgress) {
    onProgress({ phase, progress, message });
  }
}

export async function createMedicalResearchAgent(config: MedicalResearchConfig) {
  const llm = createLLM(config.llmProvider, config.model, config.apiKey);

  // Build tool map for subagent access
  const toolMap = new Map<string, DynamicStructuredTool>();
  for (const tool of allMedicalTools) {
    toolMap.set(tool.name, tool as DynamicStructuredTool);
  }

  // Create middleware tools
  const writeTodosTool = createWriteTodosTool(config.researchId);
  const filesystemTools = createFilesystemTools(config.researchId);
  const subagentConfig: SubagentConfig = {
    researchId: config.researchId,
    apiKey: config.apiKey,
    provider: config.llmProvider,
    model: FAST_MODELS[config.llmProvider] || FAST_MODELS.openai,
    ncbiApiKey: config.ncbiApiKey,
    scopusApiKey: config.scopusApiKey,
  };
  const taskTool = createTaskTool(subagentConfig, toolMap);

  // Combine all tools
  const allTools = [
    ...allMedicalTools,
    writeTodosTool,
    ...filesystemTools,
    taskTool,
  ];

  const llmWithTools = llm.bindTools(allTools);
  const baseToolNode = new ToolNode(allTools);
  const fastModel = FAST_MODELS[config.llmProvider] || FAST_MODELS.openai;

  // Track tool calls
  let toolCallCount = 0;
  const maxToolCalls = 15;

  // Wrapped tool node with tracking and API key injection
  async function toolNodeWithTracking(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const lastMessage = state.messages[state.messages.length - 1];
    let toolCalls = ("tool_calls" in lastMessage && Array.isArray(lastMessage.tool_calls))
      ? lastMessage.tool_calls
      : [];

    // Inject API keys
    toolCalls = toolCalls.map((tc: { name: string; args?: Record<string, unknown>; id?: string }) => {
      const args = { ...tc.args };
      const toolName = tc.name;

      if (toolName === "scopus_search" && config.scopusApiKey && !args.apiKey) {
        args.apiKey = config.scopusApiKey;
      }
      if (toolName === "pubmed_search" && config.ncbiApiKey && !args.apiKey) {
        args.apiKey = config.ncbiApiKey;
      }

      const llmPoweredTools = [
        "population_validator",
        "query_context_analyzer",
        "pico_query_builder",
        "pcc_query_builder",
      ];

      if (llmPoweredTools.includes(toolName)) {
        if (!args.apiKey) args.apiKey = config.apiKey;
        if (!args.provider) args.provider = config.llmProvider;
        if (!args.model) args.model = fastModel;
      }

      if ((toolName === "pico_query_builder" || toolName === "pcc_query_builder") &&
          args.enhanced === undefined && config.apiKey) {
        args.enhanced = true;
      }

      if (toolName === "claim_verifier") {
        if (!args.apiKey) args.apiKey = config.apiKey;
        if (!args.provider) args.provider = config.llmProvider;
        if (!args.model) args.model = fastModel;
        if (!args.ncbiApiKey && config.ncbiApiKey) args.ncbiApiKey = config.ncbiApiKey;
      }

      return { ...tc, args };
    });

    if ("tool_calls" in lastMessage) {
      (lastMessage as { tool_calls: typeof toolCalls }).tool_calls = toolCalls;
    }

    const startTime = Date.now();
    const newExecutions: ToolExecution[] = toolCalls.map((tc: { name: string; args?: Record<string, unknown> }) => ({
      tool: tc.name,
      status: "running" as const,
      query: tc.args?.query as string || tc.args?.term as string || JSON.stringify(tc.args || {}).substring(0, 100),
      startTime,
    }));

    // Determine phase from tool calls
    const hasSearchTools = toolCalls.some((tc: { name: string }) =>
      ["pubmed_search", "scopus_search", "cochrane_search", "openalex_search", "semantic_scholar_search", "task"].includes(tc.name)
    );
    const phase = hasSearchTools ? "searching" : "planning";

    await updateProgress(
      config.researchId,
      phase,
      Math.min(30 + toolCallCount * 3, 70),
      `Running ${toolCalls.map((tc: { name: string }) => tc.name).join(", ")}`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...newExecutions] },
      config.onProgress
    );

    const result = await baseToolNode.invoke(state);
    const endTime = Date.now();
    const duration = (endTime - startTime) / 1000;

    const completedExecutions: ToolExecution[] = newExecutions.map((exec) => ({
      ...exec,
      status: "completed" as const,
      duration,
    }));

    await updateProgress(
      config.researchId,
      phase,
      Math.min(35 + toolCallCount * 3, 75),
      `Completed ${toolCalls.map((tc: { name: string }) => tc.name).join(", ")}`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...completedExecutions] },
      config.onProgress
    );

    // Extract search results
    const extractedResults: unknown[] = [];
    if (result.messages && Array.isArray(result.messages)) {
      for (const msg of result.messages) {
        if (msg && typeof msg === "object" && "content" in msg) {
          try {
            const content = typeof msg.content === "string" ? msg.content : "";
            const parsed = JSON.parse(content);
            if (parsed.success && parsed.articles && Array.isArray(parsed.articles)) {
              const toolName = "name" in msg ? msg.name : "";
              const sourceMap: Record<string, string> = {
                scopus_search: "scopus",
                cochrane_search: "cochrane",
                openalex_search: "openalex",
                semantic_scholar_search: "semantic_scholar",
              };
              const source = sourceMap[toolName] || "pubmed";
              for (const article of parsed.articles) {
                extractedResults.push({
                  ...article,
                  authors: normalizeAuthors(article.authors),
                  source,
                });
              }
            }
          } catch {
            // Not JSON, skip
          }
        }
      }
    }

    const searchToolsUsed = new Set<string>();
    for (const tc of toolCalls) {
      if (["pubmed_search", "cochrane_search", "scopus_search", "openalex_search", "semantic_scholar_search"].includes(tc.name)) {
        searchToolsUsed.add(tc.name);
      }
    }

    return {
      ...result,
      toolExecutions: completedExecutions,
      searchResults: extractedResults,
      searchedDatabases: searchToolsUsed,
    };
  }

  // Agent node
  async function agentNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const response = await llmWithTools.invoke(state.messages);
    return { messages: [response] };
  }

  // Dynamic minimum article threshold: 8 with Scopus, 5 without
  const minArticleThreshold = config.scopusApiKey ? 8 : 5;

  // Should continue function
  function shouldContinue(state: AgentStateType): "tools" | "mandatorySearch" | "synthesize" | "completion" {
    const lastMessage = state.messages[state.messages.length - 1];

    if (
      lastMessage &&
      "tool_calls" in lastMessage &&
      Array.isArray(lastMessage.tool_calls) &&
      lastMessage.tool_calls.length > 0
    ) {
      toolCallCount++;
      if (toolCallCount >= maxToolCalls) {
        // Force mandatory search then synthesis
        if (state.searchResults.length < minArticleThreshold) {
          return "mandatorySearch";
        }
        return "synthesize";
      }
      return "tools";
    }

    // No tool calls - check if we have enough results
    if (state.searchResults.length >= minArticleThreshold) {
      return "synthesize";
    }

    // Not enough results, try mandatory search
    return "mandatorySearch";
  }

  // Planning node - initiate research
  async function planningNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    await updateProgress(
      config.researchId,
      "planning",
      10,
      "Analyzing research question and building search strategy",
      state,
      config.onProgress
    );

    let planningPrompt: string;

    if (config.queryType === "pico" && config.picoComponents) {
      planningPrompt = `Build a PICO-based search strategy for:
Population: ${config.picoComponents.population || "Not specified"}
Intervention: ${config.picoComponents.intervention || "Not specified"}
Comparison: ${config.picoComponents.comparison || "Not specified"}
Outcome: ${config.picoComponents.outcome || "Not specified"}

First, use write_todos to create your task list.
Then use the pico_query_builder tool, followed by database searches.`;
    } else if (config.queryType === "pcc" && config.pccComponents) {
      planningPrompt = `Build a PCC-based search strategy for:
Population: ${config.pccComponents.population || "Not specified"}
Concept: ${config.pccComponents.concept || "Not specified"}
Context: ${config.pccComponents.context || "Not specified"}

First, use write_todos to create your task list.
Then use the pcc_query_builder tool, followed by database searches.`;
    } else {
      planningPrompt = `Analyze this research question and build an appropriate search strategy: "${config.query}"

First, use write_todos to create your task list.
Then determine if this is a clinical question (use PICO) or a scoping question (use PCC).
Build the appropriate query and search multiple databases.`;
    }

    return {
      messages: [new HumanMessage(planningPrompt)],
      phase: "planning",
      progress: 10,
    };
  }

  // Mandatory multi-database search
  async function mandatorySearchNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    let searchQuery = "";

    for (const msg of [...state.messages].reverse()) {
      if (msg && typeof msg === "object" && "content" in msg) {
        const content = typeof msg.content === "string" ? msg.content : "";
        const pubmedQueryMatch = content.match(/pubmedQuery['":\s]+([^"'}\n]+)/i);
        if (pubmedQueryMatch) {
          searchQuery = pubmedQueryMatch[1].trim();
          break;
        }
        const quotedMatch = content.match(/["']([^"']{20,}(?:AND|OR)[^"']+)["']/);
        if (quotedMatch) {
          searchQuery = quotedMatch[1];
          break;
        }
      }
    }

    if (!searchQuery) {
      if (config.picoComponents) {
        const parts = [
          config.picoComponents.population,
          config.picoComponents.intervention,
          config.picoComponents.comparison,
          config.picoComponents.outcome,
        ].filter(Boolean);
        searchQuery = parts.join(" AND ");
      } else if (config.pccComponents) {
        const parts = [
          config.pccComponents.population,
          config.pccComponents.concept,
          config.pccComponents.context,
        ].filter(Boolean);
        searchQuery = parts.join(" AND ");
      } else {
        searchQuery = config.query;
      }
    }

    if (!searchQuery) {
      return { phase: "searching" };
    }

    /**
     * Simplify query by removing conditions progressively
     * Used when complex query returns 0 results
     */
    function simplifyQuery(query: string): string[] {
      const simplifiedQueries: string[] = [query];

      // Strategy 1: Remove outcome-related terms (often most restrictive)
      const withoutOutcome = query
        .replace(/\s+AND\s+\([^)]*(?:stroke|mortality|death|outcome|endpoint|event)[^)]*\)/gi, "")
        .replace(/\s+AND\s+[^(]*(?:stroke|mortality|death|outcome|endpoint|event)[^)AND]*/gi, "")
        .trim();
      if (withoutOutcome !== query && withoutOutcome.length > 10) {
        simplifiedQueries.push(withoutOutcome);
      }

      // Strategy 2: Keep only P and I (population and intervention)
      if (config.picoComponents) {
        const pAndI = [
          config.picoComponents.population,
          config.picoComponents.intervention,
        ].filter(Boolean).join(" AND ");
        if (pAndI && pAndI !== query) {
          simplifiedQueries.push(pAndI);
        }
      }

      // Strategy 3: Use just the main concepts (extract key terms)
      const keyTerms = query
        .replace(/\[MeSH\]/gi, "")
        .replace(/\[tiab\]/gi, "")
        .replace(/\[majr\]/gi, "")
        .replace(/["']/g, "")
        .split(/\s+(?:AND|OR)\s+/i)
        .map(t => t.trim())
        .filter(t => t.length > 3 && !t.match(/^\(|\)$/))
        .slice(0, 3)
        .join(" ");
      if (keyTerms && keyTerms.length > 10) {
        simplifiedQueries.push(keyTerms);
      }

      return simplifiedQueries;
    }

    const queryVariants = simplifyQuery(searchQuery);

    await updateProgress(
      config.researchId,
      "searching",
      50,
      "Running mandatory multi-database search",
      state,
      config.onProgress
    );

    const allResults: unknown[] = [];
    const executions: ToolExecution[] = [];
    const startTime = Date.now();
    const alreadySearched = state.searchedDatabases || new Set<string>();

    // PubMed
    if (!alreadySearched.has("pubmed_search")) {
      try {
        executions.push({ tool: "pubmed_search", status: "running", query: searchQuery, startTime });
        const pubmedResult = await pubmedSearchTool.invoke({
          query: searchQuery,
          maxResults: 30,
          apiKey: config.ncbiApiKey,
          searchStrategy: "comprehensive",
        });
        const pubmedData = JSON.parse(pubmedResult);
        if (pubmedData.success && pubmedData.articles) {
          for (const article of pubmedData.articles) {
            allResults.push({
              ...article,
              authors: normalizeAuthors(article.authors),
              source: "pubmed",
            });
          }
        }
        executions.push({
          tool: "pubmed_search",
          status: "completed",
          query: searchQuery,
          resultCount: pubmedData.articles?.length || 0,
          duration: (Date.now() - startTime) / 1000,
          startTime,
        });
      } catch (error) {
        executions.push({
          tool: "pubmed_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime,
        });
      }
    }

    // Cochrane
    if (!alreadySearched.has("cochrane_search")) {
      try {
        const cochraneStartTime = Date.now();
        executions.push({ tool: "cochrane_search", status: "running", query: searchQuery, startTime: cochraneStartTime });
        const cochraneResult = await cochraneSearchTool.invoke({
          query: searchQuery,
          maxResults: 10,
        });
        const cochraneData = JSON.parse(cochraneResult);
        if (cochraneData.success && cochraneData.reviews) {
          for (const review of cochraneData.reviews) {
            allResults.push({
              ...review,
              authors: normalizeAuthors(review.authors),
              source: "cochrane",
              pmid: review.id,
            });
          }
        }
        executions.push({
          tool: "cochrane_search",
          status: "completed",
          query: searchQuery,
          resultCount: cochraneData.reviews?.length || 0,
          duration: (Date.now() - cochraneStartTime) / 1000,
          startTime: cochraneStartTime,
        });
      } catch (error) {
        executions.push({
          tool: "cochrane_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime: Date.now(),
        });
      }
    }

    // Scopus
    if (config.scopusApiKey && !alreadySearched.has("scopus_search")) {
      try {
        const scopusStartTime = Date.now();
        const scopusQuery = config.picoComponents
          ? buildScopusQueryFromPICO(config.picoComponents)
          : convertToScopusQuery(searchQuery);

        if (scopusQuery) {
          executions.push({ tool: "scopus_search", status: "running", query: scopusQuery, startTime: scopusStartTime });
          const scopusResult = await scopusSearchTool.invoke({
            query: scopusQuery,
            maxResults: 20,
            apiKey: config.scopusApiKey,
            sortBy: "pubyear",
          });
          const scopusData = JSON.parse(scopusResult);
          if (scopusData.success && scopusData.articles) {
            for (const article of scopusData.articles) {
              allResults.push({
                ...article,
                authors: normalizeAuthors(article.authors),
                source: "scopus",
                pmid: article.scopusId,
              });
            }
          }
          executions.push({
            tool: "scopus_search",
            status: "completed",
            query: searchQuery,
            resultCount: scopusData.articles?.length || 0,
            duration: (Date.now() - scopusStartTime) / 1000,
            startTime: scopusStartTime,
          });
        }
      } catch (error) {
        executions.push({
          tool: "scopus_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime: Date.now(),
        });
      }
    }

    // OpenAlex (free fallback when Scopus unavailable)
    if (!config.scopusApiKey && !alreadySearched.has("openalex_search")) {
      try {
        const oaStartTime = Date.now();
        executions.push({ tool: "openalex_search", status: "running", query: searchQuery, startTime: oaStartTime });
        const oaResult = await openalexSearchTool.invoke({
          query: searchQuery,
          maxResults: 15,
        });
        const oaData = JSON.parse(oaResult);
        if (oaData.success && oaData.articles) {
          for (const article of oaData.articles) {
            allResults.push({
              ...article,
              authors: normalizeAuthors(article.authors),
              source: "openalex",
            });
          }
        }
        executions.push({
          tool: "openalex_search",
          status: "completed",
          query: searchQuery,
          resultCount: oaData.articles?.length || 0,
          duration: (Date.now() - oaStartTime) / 1000,
          startTime: oaStartTime,
        });
      } catch (error) {
        executions.push({
          tool: "openalex_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime: Date.now(),
        });
      }
    }

    // Semantic Scholar (free fallback when Scopus unavailable)
    if (!config.scopusApiKey && !alreadySearched.has("semantic_scholar_search")) {
      try {
        const s2StartTime = Date.now();
        executions.push({ tool: "semantic_scholar_search", status: "running", query: searchQuery, startTime: s2StartTime });
        const s2Result = await semanticScholarSearchTool.invoke({
          query: searchQuery,
          maxResults: 15,
        });
        const s2Data = JSON.parse(s2Result);
        if (s2Data.success && s2Data.articles) {
          for (const article of s2Data.articles) {
            allResults.push({
              ...article,
              authors: normalizeAuthors(article.authors),
              source: "semantic_scholar",
            });
          }
        }
        executions.push({
          tool: "semantic_scholar_search",
          status: "completed",
          query: searchQuery,
          resultCount: s2Data.articles?.length || 0,
          duration: (Date.now() - s2StartTime) / 1000,
          startTime: s2StartTime,
        });
      } catch (error) {
        executions.push({
          tool: "semantic_scholar_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime: Date.now(),
        });
      }
    }

    // If 0 results, try simplified queries as fallback
    if (allResults.length === 0 && queryVariants.length > 1) {
      console.log(`[MandatorySearch] 0 results with main query, trying ${queryVariants.length - 1} simplified queries`);

      for (let i = 1; i < queryVariants.length; i++) {
        const fallbackQuery = queryVariants[i];
        console.log(`[MandatorySearch] Trying fallback query ${i}: ${fallbackQuery.substring(0, 100)}...`);

        try {
          const fallbackStartTime = Date.now();
          executions.push({ tool: "pubmed_search", status: "running", query: fallbackQuery, startTime: fallbackStartTime });

          const pubmedResult = await pubmedSearchTool.invoke({
            query: fallbackQuery,
            maxResults: 30,
            apiKey: config.ncbiApiKey,
            searchStrategy: "comprehensive",
          });

          const pubmedData = JSON.parse(pubmedResult);
          if (pubmedData.success && pubmedData.articles && pubmedData.articles.length > 0) {
            for (const article of pubmedData.articles) {
              allResults.push({
                ...article,
                authors: normalizeAuthors(article.authors),
                source: "pubmed",
              });
            }
            executions.push({
              tool: "pubmed_search",
              status: "completed",
              query: fallbackQuery,
              resultCount: pubmedData.articles.length,
              duration: (Date.now() - fallbackStartTime) / 1000,
              startTime: fallbackStartTime,
            });
            console.log(`[MandatorySearch] Fallback query ${i} found ${pubmedData.articles.length} results`);
            break; // Found results, stop trying fallbacks
          }
        } catch (error) {
          console.log(`[MandatorySearch] Fallback query ${i} failed: ${error}`);
        }
      }
    }

    // Deduplicate results by PMID or DOI
    // Priority: pubmed > cochrane > scopus > semantic_scholar > openalex
    const sourcePriority: Record<string, number> = {
      pubmed: 0,
      cochrane: 1,
      scopus: 2,
      semantic_scholar: 3,
      openalex: 4,
    };

    const seenPmids = new Map<string, number>();
    const seenDois = new Map<string, number>();
    const deduplicatedResults: unknown[] = [];

    for (const result of allResults) {
      const r = result as PersistableResult & { pmid?: string; doi?: string };
      const source = r.source || "other";
      const priority = sourcePriority[source] ?? 5;
      let isDuplicate = false;

      if (r.pmid) {
        const existingPriority = seenPmids.get(r.pmid);
        if (existingPriority !== undefined) {
          if (priority < existingPriority) {
            // Replace existing with higher-priority source
            const idx = deduplicatedResults.findIndex((d) => {
              const dd = d as PersistableResult & { pmid?: string };
              return dd.pmid === r.pmid;
            });
            if (idx >= 0) deduplicatedResults[idx] = result;
            seenPmids.set(r.pmid, priority);
          }
          isDuplicate = true;
        } else {
          seenPmids.set(r.pmid, priority);
        }
      }

      if (!isDuplicate && r.doi) {
        const normalizedDoi = r.doi.toLowerCase();
        const existingPriority = seenDois.get(normalizedDoi);
        if (existingPriority !== undefined) {
          if (priority < existingPriority) {
            const idx = deduplicatedResults.findIndex((d) => {
              const dd = d as PersistableResult & { doi?: string };
              return dd.doi?.toLowerCase() === normalizedDoi;
            });
            if (idx >= 0) deduplicatedResults[idx] = result;
            seenDois.set(normalizedDoi, priority);
          }
          isDuplicate = true;
        } else {
          seenDois.set(normalizedDoi, priority);
        }
      }

      if (!isDuplicate) {
        deduplicatedResults.push(result);
      }
    }

    const removedCount = allResults.length - deduplicatedResults.length;
    if (removedCount > 0) {
      console.log(`[MandatorySearch] Deduplicated: removed ${removedCount} duplicates (${allResults.length} → ${deduplicatedResults.length})`);
    }

    await updateProgress(
      config.researchId,
      "searching",
      60,
      `Found ${deduplicatedResults.length} articles from mandatory multi-database search`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...executions] },
      config.onProgress
    );

    return {
      phase: "searching",
      searchResults: deduplicatedResults,
      toolExecutions: executions,
    };
  }

  // Synthesis node - actually calls LLM to generate report
  async function synthesisNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    await updateProgress(
      config.researchId,
      "synthesizing",
      75,
      "Synthesizing findings into report",
      state,
      config.onProgress
    );

    const searchResultsContext = state.searchResults
      .filter((r): r is PersistableResult => r !== null && typeof r === "object" && "title" in r)
      .slice(0, 30)
      .map((r, i) => {
        const result = r as PersistableResult & { conclusion?: string; results?: string };
        return `
[${i + 1}] ${result.title}
Authors: ${Array.isArray(result.authors) ? result.authors.slice(0, 3).join(", ") : result.authors || "Unknown"}
Journal: ${result.journal || "Unknown"} (${result.publicationYear || "N/A"})
Evidence Level: ${result.evidenceLevel || "Not classified"}
${result.conclusion ? `CONCLUSION: ${result.conclusion}` : ""}
${result.results ? `RESULTS: ${result.results}` : ""}
ABSTRACT: ${result.abstract || "No abstract available"}
PMID: ${result.pmid || "N/A"} | DOI: ${result.doi || "N/A"}
---`;
      })
      .join("\n");

    const sourceCount = state.searchResults
      .filter((r): r is PersistableResult => r !== null && typeof r === "object" && "title" in r)
      .slice(0, 30).length;

    // Determine which databases were actually searched from results
    const sourceDisplayNames: Record<string, string> = {
      pubmed: "PubMed",
      cochrane: "Cochrane Library",
      scopus: "Scopus",
      openalex: "OpenAlex",
      semantic_scholar: "Semantic Scholar",
    };
    const actualSources = new Set<string>();
    for (const r of state.searchResults) {
      const result = r as PersistableResult;
      if (result?.source && sourceDisplayNames[result.source]) {
        actualSources.add(sourceDisplayNames[result.source]);
      }
    }
    const databasesSearched = actualSources.size > 0
      ? Array.from(actualSources).join(", ")
      : "PubMed";

    const synthesisPrompt = `Based on the search results gathered, synthesize a comprehensive evidence-based report.

## CRITICAL ANTI-HALLUCINATION INSTRUCTIONS

**YOU MUST BASE ALL CLAIMS ON THE ACTUAL ABSTRACT TEXT PROVIDED BELOW.**
DO NOT use your training knowledge about these papers.
DO NOT infer or assume conclusions not stated in the abstracts.

For each claim about a study's findings:
1. ONLY state what the abstract/conclusion EXPLICITLY says
2. If the conclusion says "no significant difference" or "no benefit", you MUST report that
3. If the abstract is unclear about findings, state "findings unclear from abstract"
4. NEVER reverse or contradict what the actual abstract states

## CRITICAL CITATION RULES

**THERE ARE EXACTLY ${sourceCount} SOURCES AVAILABLE (numbered [1] through [${sourceCount}]).**
- You may ONLY use citation numbers [1] through [${sourceCount}]
- DO NOT use any citation number higher than [${sourceCount}]
- Every citation number MUST correspond to a source listed below

## Search Results with FULL Abstracts (${sourceCount} sources):
${searchResultsContext}

## Report Structure

Use numbered in-text citations [1], [2], [3], etc.
Maximum citation number is [${sourceCount}].
Include a complete "References" section at the end using Vancouver style.

Structure:
1. Executive Summary
2. Background
3. Methods - **State that the following databases were searched: ${databasesSearched}**
4. Results (by evidence level, with citations)
5. Discussion
6. Conclusions
7. References (Vancouver format)

Focus on accurately representing study findings, even if negative/null results.`;

    // Actually call the LLM to generate the synthesis report
    const synthesisLLM = createLLM(config.llmProvider, config.model, config.apiKey);
    const response = await synthesisLLM.invoke([
      new SystemMessage("You are a medical research synthesizer. Generate comprehensive evidence-based reports with proper citations."),
      new HumanMessage(synthesisPrompt),
    ]);

    const synthesizedReport = typeof response.content === "string"
      ? response.content
      : JSON.stringify(response.content);

    return {
      messages: [new HumanMessage(synthesisPrompt), response],
      phase: "synthesizing",
      progress: 80,
      synthesizedContent: synthesizedReport,
    };
  }

  // Translation node
  async function translationNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    // Use synthesizedContent from state (set by synthesisNode)
    const englishReport = state.synthesizedContent || "";

    if (!englishReport) {
      // Fallback: try to get from last AI message
      const lastAIMessage = [...state.messages]
        .reverse()
        .find((m): m is AIMessage => m instanceof AIMessage);
      const fallbackReport = lastAIMessage
        ? typeof lastAIMessage.content === "string"
          ? lastAIMessage.content
          : JSON.stringify(lastAIMessage.content)
        : "";

      if (!fallbackReport) {
        return {
          phase: "translating",
          progress: 95,
          originalContent: "",
        };
      }

      // Use fallback
      return translationNode({ ...state, synthesizedContent: fallbackReport });
    }

    await updateProgress(
      config.researchId,
      "translating",
      90,
      "Translating report to Korean...",
      state,
      config.onProgress
    );

    try {
      const translatedReport = await translateReport(
        englishReport,
        config.apiKey,
        config.llmProvider,
        config.model
      );

      return {
        phase: "translating",
        progress: 95,
        synthesizedContent: translatedReport,
        originalContent: englishReport,
      };
    } catch {
      return {
        phase: "translating",
        progress: 95,
        synthesizedContent: englishReport,
        originalContent: englishReport,
      };
    }
  }

  // Completion node
  async function completionNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const hasResults = state.searchResults && state.searchResults.length > 0;
    const hasSynthesis = !!state.synthesizedContent;

    // Handle no results case
    if (!hasResults && !hasSynthesis) {
      const noResultsMessage = config.language === "ko"
        ? `# 검색 결과 없음\n\n검색 조건에 맞는 문헌을 찾을 수 없습니다.\n\n## 검색 쿼리\n${config.query}\n\n## 권장 사항\n- 검색어를 더 일반적인 용어로 변경해 보세요\n- 특정 조건(예: BMI 수치, 특정 약물명)을 제거해 보세요\n- 영어 검색어를 사용해 보세요`
        : `# No Results Found\n\nNo literature matching the search criteria was found.\n\n## Search Query\n${config.query}\n\n## Recommendations\n- Try using more general search terms\n- Remove specific conditions (e.g., exact BMI values, specific drug names)\n- Consider broadening the population criteria`;

      await updateProgress(
        config.researchId,
        "complete",
        100,
        "Research complete - No results found",
        state,
        config.onProgress
      );

      const reportId = generateId();
      const now = new Date();

      await db.insert(reports).values({
        id: reportId,
        researchId: config.researchId,
        title: `No Results: ${config.query.substring(0, 100)}`,
        content: noResultsMessage,
        originalContent: noResultsMessage,
        language: config.language || "en",
        format: "markdown",
        wordCount: noResultsMessage.split(/\s+/).length,
        referenceCount: 0,
        version: 1,
        createdAt: now,
        updatedAt: now,
      });

      await db
        .update(research)
        .set({
          status: "completed",
          progress: 100,
          completedAt: now,
          errorMessage: "No search results found matching the criteria",
        })
        .where(eq(research.id, config.researchId));

      return {
        phase: "complete",
        progress: 100,
        synthesizedContent: noResultsMessage,
      };
    }

    await updateProgress(
      config.researchId,
      "complete",
      100,
      "Research complete",
      state,
      config.onProgress
    );

    if (hasResults) {
      try {
        const persistableResults = state.searchResults
          .filter((r): r is PersistableResult => r !== null && typeof r === "object" && "title" in r)
          .map((r) => ({
            title: r.title || "Untitled",
            authors: r.authors,
            journal: r.journal,
            volume: r.volume,
            issue: r.issue,
            pages: r.pages,
            publicationYear: r.publicationYear,
            publicationDate: r.publicationDate,
            doi: r.doi,
            pmid: r.pmid,
            url: r.url,
            abstract: r.abstract,
            source: r.source || "unknown",
            evidenceLevel: r.evidenceLevel,
            citationCount: r.citationCount,
            meshTerms: r.meshTerms,
          }));
        await persistSearchResults(config.researchId, persistableResults);
      } catch (error) {
        console.error("Error persisting search results:", error);
      }
    }

    let reportContent = state.synthesizedContent;
    let originalContent = state.originalContent;
    const language = config.language || "en";

    if (!reportContent) {
      const lastAIMessage = [...state.messages]
        .reverse()
        .find((m): m is AIMessage => m instanceof AIMessage);

      reportContent = lastAIMessage
        ? typeof lastAIMessage.content === "string"
          ? lastAIMessage.content
          : JSON.stringify(lastAIMessage.content)
        : "No report content generated.";
    }

    if (language === "en") {
      originalContent = reportContent;
    }

    const reportId = generateId();
    const now = new Date();
    // Match citation patterns including combined refs like [4,5] or [1,2,3]
    const refMatches = reportContent.match(/\[[\d,\s]+\]/g) || [];
    const uniqueRefNumbers = new Set<string>();
    for (const match of refMatches) {
      // Extract all numbers from the match (handles [1], [4,5], [1, 2, 3])
      const numbers = match.match(/\d+/g) || [];
      numbers.forEach(n => uniqueRefNumbers.add(n));
    }
    const referenceCount = uniqueRefNumbers.size;

    await db.insert(reports).values({
      id: reportId,
      researchId: config.researchId,
      title: `Research Report: ${config.query.substring(0, 100)}`,
      content: reportContent,
      originalContent: originalContent || reportContent,
      language,
      format: "markdown",
      wordCount: reportContent.split(/\s+/).length,
      referenceCount,
      version: 1,
      createdAt: now,
      updatedAt: now,
    });

    await db
      .update(research)
      .set({
        status: "completed",
        progress: 100,
        completedAt: now,
      })
      .where(eq(research.id, config.researchId));

    // Update final todos
    const todos = await db.query.researchTodos.findMany({
      where: eq(researchTodos.researchId, config.researchId),
    });
    for (const todo of todos) {
      if (todo.status !== "completed") {
        await db
          .update(researchTodos)
          .set({ status: "completed", completedAt: now })
          .where(eq(researchTodos.id, todo.id));
      }
    }

    return {
      phase: "complete",
      progress: 100,
      synthesizedContent: reportContent,
      originalContent,
      language,
    };
  }

  // Track mandatory search attempts to prevent infinite loops
  let mandatorySearchAttempts = 0;
  const MAX_MANDATORY_SEARCH_ATTEMPTS = 2;

  // Conditional routing after mandatory search
  function shouldContinueAfterMandatorySearch(state: AgentStateType): "synthesize" | "agent" | "completion" {
    mandatorySearchAttempts++;

    // If we have enough results, synthesize
    if (state.searchResults.length >= minArticleThreshold) {
      return "synthesize";
    }

    // If we have some results (1-7), synthesize with what we have
    if (state.searchResults.length > 0) {
      console.log(`[MandatorySearch] Proceeding to synthesis with ${state.searchResults.length} results`);
      return "synthesize";
    }

    // If we've hit max attempts with 0 results, go to completion with error
    if (mandatorySearchAttempts >= MAX_MANDATORY_SEARCH_ATTEMPTS) {
      console.log(`[MandatorySearch] No results found after ${mandatorySearchAttempts} attempts, completing with no results`);
      return "completion";
    }

    // Otherwise, let agent try a different approach
    return "agent";
  }

  // Conditional routing after synthesis
  function shouldContinueAfterSynthesis(state: AgentStateType): "translation" | "completion" {
    const language = config.language || "en";
    if (language !== "en") {
      return "translation";
    }
    return "completion";
  }

  // Build the graph
  const workflow = new StateGraph(AgentState)
    .addNode("planning", planningNode)
    .addNode("agent", agentNode)
    .addNode("tools", toolNodeWithTracking)
    .addNode("mandatorySearch", mandatorySearchNode)
    .addNode("synthesis", synthesisNode)
    .addNode("translation", translationNode)
    .addNode("completion", completionNode)
    .addEdge(START, "planning")
    .addEdge("planning", "agent")
    .addConditionalEdges("agent", shouldContinue, {
      tools: "tools",
      mandatorySearch: "mandatorySearch",
      synthesize: "synthesis",
      completion: "completion",
    })
    .addEdge("tools", "agent")
    .addConditionalEdges("mandatorySearch", shouldContinueAfterMandatorySearch, {
      synthesize: "synthesis",
      agent: "agent",
      completion: "completion",
    })
    // After synthesis, decide translation vs completion (not back to agent)
    .addConditionalEdges("synthesis", shouldContinueAfterSynthesis, {
      translation: "translation",
      completion: "completion",
    })
    .addEdge("translation", "completion")
    .addEdge("completion", END);

  const graph = workflow.compile();
  return graph;
}

export async function runMedicalResearch(config: MedicalResearchConfig): Promise<AgentStateType> {
  const graph = await createMedicalResearchAgent(config);

  const initialState = {
    messages: [new SystemMessage(getSystemPrompt(config))],
    researchId: config.researchId,
    phase: "init",
    progress: 0,
    planningSteps: [],
    toolExecutions: [],
    searchResults: [],
    synthesizedContent: "",
    language: config.language || ("en" as Locale),
    originalContent: "",
  };

  if (config.queryType === "pico" && config.picoComponents) {
    await db.insert(picoQueries).values({
      id: generateId(),
      researchId: config.researchId,
      population: config.picoComponents.population,
      intervention: config.picoComponents.intervention,
      comparison: config.picoComponents.comparison,
      outcome: config.picoComponents.outcome,
      createdAt: new Date(),
    });
  } else if (config.queryType === "pcc" && config.pccComponents) {
    await db.insert(pccQueries).values({
      id: generateId(),
      researchId: config.researchId,
      population: config.pccComponents.population,
      concept: config.pccComponents.concept,
      context: config.pccComponents.context,
      createdAt: new Date(),
    });
  }

  const finalState = await graph.invoke(initialState);
  return finalState;
}
