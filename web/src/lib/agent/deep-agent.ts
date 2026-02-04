import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { HumanMessage, SystemMessage, AIMessage } from "@langchain/core/messages";
import { StateGraph, Annotation, START, END } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { allMedicalTools, calculateCompositeScore, type EvidenceLevel } from "./tools";
import { db } from "@/db";
import { research, agentStates, reports, picoQueries, pccQueries, searchResults } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";
import { exportStateToMarkdown } from "../state-export";
import { formatVancouverCitation, type CitationData } from "@/lib/citation/vancouver";

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
      // Merge: update existing or add new
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
  onProgress?: (progress: { phase: string; progress: number; message: string }) => void;
}

const SYSTEM_PROMPT = `You are a Medical Research Agent specialized in evidence-based medicine and systematic literature review.

Your capabilities:
1. Build optimized search queries using PICO or PCC frameworks
2. Search medical databases (PubMed, Scopus, Cochrane Library)
3. Map terms to MeSH headings for better search results
4. Classify evidence levels (Level I-V)
5. Synthesize findings into comprehensive reports

When conducting research:
1. First analyze the research question and identify key concepts
2. Build a structured search query using PICO (for clinical questions) or PCC (for qualitative/scoping reviews)
3. Search multiple databases, prioritizing Cochrane for systematic reviews
4. Evaluate evidence quality and extract key findings
5. Synthesize results into a structured report with citations

Always prioritize:
- High-quality evidence (systematic reviews, RCTs)
- Recent publications (within last 5-10 years unless historical context needed)
- Studies with clear methodology
- Diverse perspectives when evidence is conflicting

Format your final report in markdown with:
- Executive summary
- Background
- Methods (search strategy, databases, inclusion criteria)
- Results (organized by evidence level)
- Discussion
- Conclusions
- References (with PMIDs/DOIs)`;

function createLLM(
  provider: "openai" | "anthropic" | "google",
  model: string,
  apiKey: string
): ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI {
  if (provider === "anthropic") {
    return new ChatAnthropic({
      modelName: model,
      anthropicApiKey: apiKey,
      temperature: 0.3,
    });
  }
  if (provider === "google") {
    return new ChatGoogleGenerativeAI({
      model: model,
      apiKey: apiKey,
      temperature: 0.3,
    });
  }
  return new ChatOpenAI({
    modelName: model,
    openAIApiKey: apiKey,
    temperature: 0.3,
  });
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

  // Calculate scores and sort
  const scoredResults = results.map((result) => {
    const scores = calculateCompositeScore(
      result.evidenceLevel as EvidenceLevel | undefined,
      result.citationCount,
      result.publicationDate || result.publicationYear
    );
    return { ...result, ...scores };
  });

  // Sort by composite score
  scoredResults.sort((a, b) => b.compositeScore - a.compositeScore);

  // Insert with reference numbers
  for (let i = 0; i < scoredResults.length; i++) {
    const result = scoredResults[i];
    const refNumber = i + 1;

    // Generate Vancouver citation
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

  // Update research status
  await db
    .update(research)
    .set({
      status: phase === "complete" ? "completed" : "running",
      progress,
    })
    .where(eq(research.id, researchId));

  // Determine active agents based on phase
  const activeAgents = [];
  if (phase === "planning") {
    activeAgents.push({ name: "Query Builder", status: "active" });
  } else if (phase === "searching") {
    activeAgents.push({ name: "Database Search", status: "active" });
  } else if (phase === "synthesizing") {
    activeAgents.push({ name: "Report Generator", status: "active" });
  }

  // Save agent state
  await db.insert(agentStates).values({
    id: stateId,
    researchId,
    phase,
    message,
    overallProgress: progress,
    planningSteps: JSON.stringify(state.planningSteps || []),
    activeAgents: JSON.stringify(activeAgents),
    toolExecutions: JSON.stringify(state.toolExecutions || []),
    createdAt: now,
    updatedAt: now,
  });

  // Export to markdown
  await exportStateToMarkdown(researchId, phase, state);

  // Callback
  if (onProgress) {
    onProgress({ phase, progress, message });
  }
}

export async function createMedicalResearchAgent(config: MedicalResearchConfig) {
  const llm = createLLM(config.llmProvider, config.model, config.apiKey);
  const llmWithTools = llm.bindTools(allMedicalTools);

  // Original tool node
  const baseToolNode = new ToolNode(allMedicalTools);

  // Wrapped tool node that tracks executions
  async function toolNodeWithTracking(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const lastMessage = state.messages[state.messages.length - 1];
    const toolCalls = ("tool_calls" in lastMessage && Array.isArray(lastMessage.tool_calls))
      ? lastMessage.tool_calls
      : [];

    // Create execution entries for tools about to run
    const startTime = Date.now();
    const newExecutions: ToolExecution[] = toolCalls.map((tc: { name: string; args?: Record<string, unknown> }) => ({
      tool: tc.name,
      status: "running" as const,
      query: tc.args?.query as string || tc.args?.term as string || JSON.stringify(tc.args || {}).substring(0, 100),
      startTime,
    }));

    // Update progress to show tools running
    await updateProgress(
      config.researchId,
      "searching",
      Math.min(30 + toolCallCount * 5, 60),
      `Running ${toolCalls.map((tc: { name: string }) => tc.name).join(", ")}`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...newExecutions] },
      config.onProgress
    );

    // Run the actual tools
    const result = await baseToolNode.invoke(state);
    const endTime = Date.now();
    const duration = (endTime - startTime) / 1000;

    // Update executions with results
    const completedExecutions: ToolExecution[] = newExecutions.map((exec) => ({
      ...exec,
      status: "completed" as const,
      duration,
    }));

    // Update progress with completed tools
    await updateProgress(
      config.researchId,
      "searching",
      Math.min(35 + toolCallCount * 5, 65),
      `Completed ${toolCalls.map((tc: { name: string }) => tc.name).join(", ")}`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...completedExecutions] },
      config.onProgress
    );

    return {
      ...result,
      toolExecutions: completedExecutions,
    };
  }

  // Agent node - decides what to do next
  async function agentNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const response = await llmWithTools.invoke(state.messages);

    return {
      messages: [response],
    };
  }

  // Track tool calls to determine when to synthesize
  let toolCallCount = 0;
  const maxToolCalls = 10; // Prevent infinite loops

  // Should continue function
  function shouldContinue(state: AgentStateType): "tools" | "synthesize" | typeof END {
    const lastMessage = state.messages[state.messages.length - 1];

    if (
      lastMessage &&
      "tool_calls" in lastMessage &&
      Array.isArray(lastMessage.tool_calls) &&
      lastMessage.tool_calls.length > 0
    ) {
      toolCallCount++;
      // If we've made enough tool calls, force synthesis
      if (toolCallCount >= maxToolCalls) {
        return "synthesize";
      }
      return "tools";
    }

    // Check if we're in searching phase and have made at least one tool call
    if (state.phase === "searching" && toolCallCount > 0) {
      return "synthesize";
    }

    // If we've completed planning and agent returns without tool calls, synthesize
    if (state.phase === "planning" && toolCallCount > 0) {
      return "synthesize";
    }

    return END;
  }

  // Planning node
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

Use the pico_query_builder tool first, then search PubMed and Cochrane.`;
    } else if (config.queryType === "pcc" && config.pccComponents) {
      planningPrompt = `Build a PCC-based search strategy for:
Population: ${config.pccComponents.population || "Not specified"}
Concept: ${config.pccComponents.concept || "Not specified"}
Context: ${config.pccComponents.context || "Not specified"}

Use the pcc_query_builder tool first, then search PubMed.`;
    } else {
      planningPrompt = `Analyze this research question and build an appropriate search strategy: "${config.query}"

First determine if this is a clinical question (use PICO) or a scoping/qualitative question (use PCC).
Then build the appropriate query and search multiple databases.`;
    }

    return {
      messages: [new HumanMessage(planningPrompt)],
      phase: "planning",
      progress: 10,
      planningSteps: [
        { id: "1", name: "Analyze question", status: "completed" },
        { id: "2", name: "Build search query", status: "in_progress" },
        { id: "3", name: "Search databases", status: "pending" },
        { id: "4", name: "Synthesize results", status: "pending" },
      ],
    };
  }

  // Search node
  async function searchNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    await updateProgress(
      config.researchId,
      "searching",
      40,
      "Searching medical databases",
      state,
      config.onProgress
    );

    return {
      phase: "searching",
      progress: 40,
      planningSteps: state.planningSteps.map((step) =>
        step.id === "2"
          ? { ...step, status: "completed" }
          : step.id === "3"
            ? { ...step, status: "in_progress" }
            : step
      ),
    };
  }

  // Synthesis node
  async function synthesisNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    await updateProgress(
      config.researchId,
      "synthesizing",
      70,
      "Synthesizing findings into report",
      state,
      config.onProgress
    );

    const synthesisPrompt = `Based on the search results gathered, synthesize a comprehensive evidence-based report.

IMPORTANT: When citing sources, use numbered in-text citations [1], [2], [3], etc.
Assign reference numbers in order of first citation in the text.
Include a complete "References" section at the end using Vancouver style:

Example Vancouver format:
1. Smith AB, Jones CD. Title of article. Journal Name. 2024;45(3):123-130. doi:10.1000/example

Structure the report with:
1. Executive Summary
2. Background
3. Methods (search strategy used)
4. Results (organized by evidence level, with [n] citations)
5. Discussion
6. Conclusions
7. References (numbered list in Vancouver format)

Focus on:
- Highlighting the highest quality evidence
- Noting any conflicting findings
- Identifying gaps in the literature
- Providing clinical implications where appropriate
- Using proper in-text citations [1], [2], etc. throughout`;

    return {
      messages: [new HumanMessage(synthesisPrompt)],
      phase: "synthesizing",
      progress: 70,
      planningSteps: state.planningSteps.map((step) =>
        step.id === "3"
          ? { ...step, status: "completed" }
          : step.id === "4"
            ? { ...step, status: "in_progress" }
            : step
      ),
    };
  }

  // Completion node
  async function completionNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    await updateProgress(
      config.researchId,
      "complete",
      100,
      "Research complete",
      state,
      config.onProgress
    );

    // Persist search results if available
    if (state.searchResults && state.searchResults.length > 0) {
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

    // Extract the final report from messages
    const lastAIMessage = [...state.messages]
      .reverse()
      .find((m): m is AIMessage => m instanceof AIMessage);

    const reportContent = lastAIMessage
      ? typeof lastAIMessage.content === "string"
        ? lastAIMessage.content
        : JSON.stringify(lastAIMessage.content)
      : "No report content generated.";

    // Save report to database
    const reportId = generateId();
    const now = new Date();

    // Count unique reference numbers (e.g., [1], [2], [3])
    const refMatches = reportContent.match(/\[\d+\]/g) || [];
    const uniqueRefs = new Set(refMatches.map(r => r));
    const referenceCount = uniqueRefs.size;

    await db.insert(reports).values({
      id: reportId,
      researchId: config.researchId,
      title: `Research Report: ${config.query.substring(0, 100)}`,
      content: reportContent,
      format: "markdown",
      wordCount: reportContent.split(/\s+/).length,
      referenceCount,
      version: 1,
      createdAt: now,
      updatedAt: now,
    });

    // Update research record
    await db
      .update(research)
      .set({
        status: "completed",
        progress: 100,
        completedAt: now,
      })
      .where(eq(research.id, config.researchId));

    return {
      phase: "complete",
      progress: 100,
      synthesizedContent: reportContent,
      planningSteps: state.planningSteps.map((step) => ({ ...step, status: "completed" })),
    };
  }

  // Build the graph
  const workflow = new StateGraph(AgentState)
    .addNode("planning", planningNode)
    .addNode("agent", agentNode)
    .addNode("tools", toolNodeWithTracking)
    .addNode("search", searchNode)
    .addNode("synthesis", synthesisNode)
    .addNode("completion", completionNode)
    .addEdge(START, "planning")
    .addEdge("planning", "agent")
    .addConditionalEdges("agent", shouldContinue, {
      tools: "tools",
      synthesize: "synthesis",
      [END]: "completion",
    })
    .addEdge("tools", "search")
    .addEdge("search", "agent")
    .addEdge("synthesis", "agent");

  const graph = workflow.compile();

  return graph;
}

export async function runMedicalResearch(config: MedicalResearchConfig): Promise<AgentStateType> {
  const graph = await createMedicalResearchAgent(config);

  // Initialize with system message
  const initialState = {
    messages: [new SystemMessage(SYSTEM_PROMPT)],
    researchId: config.researchId,
    phase: "init",
    progress: 0,
    planningSteps: [],
    toolExecutions: [],
    searchResults: [],
    synthesizedContent: "",
  };

  // Save PICO/PCC query if provided
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

  // Run the graph
  const finalState = await graph.invoke(initialState);

  return finalState;
}
