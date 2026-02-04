import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { HumanMessage, SystemMessage, AIMessage } from "@langchain/core/messages";
import { StateGraph, Annotation, START, END } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { allMedicalTools } from "./tools";
import { db } from "@/db";
import { research, agentStates, reports, picoQueries, pccQueries } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";
import { exportStateToMarkdown } from "../state-export";

// Agent state annotation
const AgentState = Annotation.Root({
  messages: Annotation<(HumanMessage | AIMessage | SystemMessage)[]>({
    reducer: (current, update) => current.concat(update),
    default: () => [],
  }),
  researchId: Annotation<string>(),
  phase: Annotation<string>({
    default: () => "init",
  }),
  progress: Annotation<number>({
    default: () => 0,
  }),
  planningSteps: Annotation<Array<{ id: string; name: string; status: string }>>({
    default: () => [],
  }),
  searchResults: Annotation<unknown[]>({
    reducer: (current, update) => current.concat(update),
    default: () => [],
  }),
  synthesizedContent: Annotation<string>({
    default: () => "",
  }),
});

type AgentStateType = typeof AgentState.State;

export interface MedicalResearchConfig {
  researchId: string;
  query: string;
  queryType: "pico" | "pcc" | "free";
  llmProvider: "openai" | "anthropic";
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

function createLLM(provider: "openai" | "anthropic", model: string, apiKey: string) {
  if (provider === "anthropic") {
    return new ChatAnthropic({
      modelName: model,
      anthropicApiKey: apiKey,
      temperature: 0.3,
    });
  }
  return new ChatOpenAI({
    modelName: model,
    openAIApiKey: apiKey,
    temperature: 0.3,
  });
}

async function updateProgress(
  researchId: string,
  phase: string,
  progress: number,
  message: string,
  state: Partial<AgentStateType>,
  onProgress?: (progress: { phase: string; progress: number; message: string }) => void
) {
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

  // Save agent state
  await db.insert(agentStates).values({
    id: stateId,
    researchId,
    phase,
    message,
    overallProgress: progress,
    planningSteps: JSON.stringify(state.planningSteps || []),
    activeAgents: JSON.stringify([]),
    toolExecutions: JSON.stringify([]),
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

  // Tool node
  const toolNode = new ToolNode(allMedicalTools);

  // Agent node - decides what to do next
  async function agentNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const response = await llmWithTools.invoke(state.messages);

    return {
      messages: [response],
    };
  }

  // Should continue function
  function shouldContinue(state: AgentStateType): "tools" | "synthesize" | typeof END {
    const lastMessage = state.messages[state.messages.length - 1];

    if (
      lastMessage &&
      "tool_calls" in lastMessage &&
      Array.isArray(lastMessage.tool_calls) &&
      lastMessage.tool_calls.length > 0
    ) {
      return "tools";
    }

    // Check if we have enough search results to synthesize
    if (state.searchResults.length > 0 && state.phase === "searching") {
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

Structure the report with:
1. Executive Summary
2. Background
3. Methods (search strategy used)
4. Results (organized by evidence level)
5. Discussion
6. Conclusions
7. References

Focus on:
- Highlighting the highest quality evidence
- Noting any conflicting findings
- Identifying gaps in the literature
- Providing clinical implications where appropriate`;

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

    // Extract the final report from messages
    const lastAIMessage = [...state.messages]
      .reverse()
      .find((m): m is AIMessage => m instanceof AIMessage);

    const reportContent =
      typeof lastAIMessage?.content === "string"
        ? lastAIMessage.content
        : JSON.stringify(lastAIMessage?.content);

    // Save report to database
    const reportId = generateId();
    const now = new Date();

    await db.insert(reports).values({
      id: reportId,
      researchId: config.researchId,
      title: `Research Report: ${config.query.substring(0, 100)}`,
      content: reportContent,
      format: "markdown",
      wordCount: reportContent.split(/\s+/).length,
      referenceCount: (reportContent.match(/PMID|DOI/gi) || []).length,
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
    .addNode("tools", toolNode)
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

export async function runMedicalResearch(config: MedicalResearchConfig) {
  const graph = await createMedicalResearchAgent(config);

  // Initialize with system message
  const initialState = {
    messages: [new SystemMessage(SYSTEM_PROMPT)],
    researchId: config.researchId,
    phase: "init",
    progress: 0,
    planningSteps: [],
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
