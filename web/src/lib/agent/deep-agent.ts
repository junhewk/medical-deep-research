import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";
import { HumanMessage, SystemMessage, AIMessage } from "@langchain/core/messages";
import { StateGraph, Annotation, START, END } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import {
  allMedicalTools,
  calculateCompositeScore,
  type EvidenceLevel,
  pubmedSearchTool,
  scopusSearchTool,
  cochraneSearchTool,
  convertToScopusQuery,
  buildScopusQueryFromPICO,
} from "./tools";
import { db } from "@/db";
import { research, agentStates, reports, picoQueries, pccQueries, searchResults } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateId } from "@/lib/utils";
import { exportStateToMarkdown } from "../state-export";
import { formatVancouverCitation, type CitationData } from "@/lib/citation/vancouver";

/**
 * Normalize authors field: convert string to array if needed
 * Handles formats like "Smith AB, Jones CD et al."
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
 * Fast model for each LLM provider (used for population validation)
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
5. Validate study populations against target criteria
6. Synthesize findings into comprehensive reports

## Search Strategy Guidelines

### For Clinical Questions (PICO)
**CRITICAL: Use "comprehensive" search strategy** to prioritize recent landmark trials:
- Always set searchStrategy: "comprehensive" when calling pubmed_search
- This ensures recent RCTs (last 3 years) from NEJM, Lancet, JAMA are prioritized
- Prevents older high-citation papers from overshadowing recent definitive trials

### Population Matching
**CRITICAL: Validate population matches** to avoid evidence misapplication:
- If query specifies LVEF >= 50% (preserved EF), exclude HFrEF studies (LVEF < 40%)
- If query specifies acute MI, distinguish from chronic heart failure studies
- Use the population_validator tool to verify study populations match criteria
- Flag or exclude studies with clear population mismatches

### Numeric Criteria
Pay attention to numeric thresholds in queries:
- LVEF >= 50% = preserved ejection fraction (HFpEF)
- LVEF 40-49% = mildly reduced (HFmrEF)
- LVEF < 40% = reduced ejection fraction (HFrEF)
- These populations have DIFFERENT treatment responses

### Clinical Context Distinctions
Never conflate:
- Acute MI (post-infarction) ≠ Chronic heart failure
- Primary prevention ≠ Secondary prevention
- Inpatient/ICU setting ≠ Outpatient/clinic

## Research Workflow

1. **Analyze** the research question and identify:
   - Key PICO/PCC components
   - Numeric criteria (LVEF, age, eGFR thresholds)
   - Clinical context (acute vs chronic, inpatient vs outpatient)

2. **Build search query** using PICO or PCC framework:
   - Query builder automatically generates exclusion terms
   - Review generated exclusions to ensure population targeting

3. **Search multiple databases** with appropriate strategy:
   - Use "comprehensive" strategy for clinical questions in PubMed
   - **Always search both PubMed AND Scopus** for comprehensive coverage
   - Scopus provides citation counts and covers different journals
   - Search Cochrane for existing systematic reviews
   - API keys are automatically injected - just call the tools without specifying apiKey

4. **Validate populations** for top results:
   - Use population_validator tool for key studies
   - Exclude or flag studies with population mismatches
   - Document exclusion reasons

5. **Synthesize** findings with population awareness:
   - Only include studies with matching populations
   - Note any population limitations in applicability
   - Highlight recent landmark trials that directly answer the question

## Prioritization Criteria
1. Recent RCTs from landmark journals (NEJM, Lancet, JAMA, Circulation)
2. Studies with exact population match
3. Systematic reviews/meta-analyses from last 5 years
4. Large, well-designed observational studies if RCTs unavailable

## Report Format (Markdown)
- Executive summary (highlight key finding, cite landmark trial)
- Background
- Methods (search strategy, databases, population criteria)
- Results (organized by evidence level, note population characteristics)
- Discussion (address population-specific considerations)
- Conclusions
- References (with PMIDs/DOIs, note journal)

## Post-Synthesis Verification

After synthesizing findings into a report, consider using the claim_verifier tool to validate your claims:
- Verifies PMIDs exist in PubMed
- Fetches actual abstracts and compares against your claims
- Flags any directional mismatches (e.g., claiming "benefit" when study found "no benefit")

This is especially important for clinical questions where accurate representation of findings is critical.`;

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

  // Wrapped tool node that tracks executions and injects API keys
  async function toolNodeWithTracking(state: AgentStateType): Promise<Partial<AgentStateType>> {
    const lastMessage = state.messages[state.messages.length - 1];
    let toolCalls = ("tool_calls" in lastMessage && Array.isArray(lastMessage.tool_calls))
      ? lastMessage.tool_calls
      : [];

    // Inject API keys into tool calls that need them
    toolCalls = toolCalls.map((tc: { name: string; args?: Record<string, unknown>; id?: string }) => {
      const args = { ...tc.args };

      // Inject Scopus API key
      if (tc.name === "scopus_search" && config.scopusApiKey && !args.apiKey) {
        args.apiKey = config.scopusApiKey;
      }

      // Inject NCBI API key for PubMed
      if (tc.name === "pubmed_search" && config.ncbiApiKey && !args.apiKey) {
        args.apiKey = config.ncbiApiKey;
      }

      // Inject API key and provider for population validator
      // Uses the same LLM provider the user configured (not hardcoded OpenAI)
      if (tc.name === "population_validator") {
        if (!args.apiKey) {
          args.apiKey = config.apiKey;
        }
        if (!args.provider) {
          args.provider = config.llmProvider;
        }
        if (!args.model) {
          args.model = FAST_MODELS[config.llmProvider] || FAST_MODELS.openai;
        }
      }

      // Inject API key and provider for claim verifier
      if (tc.name === "claim_verifier") {
        if (!args.apiKey) {
          args.apiKey = config.apiKey;
        }
        if (!args.llmProvider) {
          args.llmProvider = config.llmProvider;
        }
        if (!args.model) {
          args.model = FAST_MODELS[config.llmProvider] || FAST_MODELS.openai;
        }
        if (!args.ncbiApiKey && config.ncbiApiKey) {
          args.ncbiApiKey = config.ncbiApiKey;
        }
      }

      return { ...tc, args };
    });

    // Update the message with injected API keys
    if ("tool_calls" in lastMessage) {
      (lastMessage as { tool_calls: typeof toolCalls }).tool_calls = toolCalls;
    }

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

    // Extract search results from tool responses for persistence
    const extractedResults: unknown[] = [];
    if (result.messages && Array.isArray(result.messages)) {
      for (const msg of result.messages) {
        if (msg && typeof msg === "object" && "content" in msg) {
          try {
            const content = typeof msg.content === "string" ? msg.content : "";
            const parsed = JSON.parse(content);
            if (parsed.success && parsed.articles && Array.isArray(parsed.articles)) {
              // Add source info based on tool name
              const toolName = "name" in msg ? msg.name : "";
              const sourceMap: Record<string, string> = {
                scopus_search: "scopus",
                cochrane_search: "cochrane",
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
            // Not JSON or not a search result, skip
          }
        }
      }
    }

    return {
      ...result,
      toolExecutions: completedExecutions,
      searchResults: extractedResults,
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

  /**
   * MANDATORY MULTI-DATABASE SEARCH NODE
   *
   * This node ensures ALL configured databases are searched regardless of LLM decisions.
   * Problem solved: Agent sometimes decides not to call Scopus even when API key is configured.
   *
   * Search strategy:
   * - ALWAYS call PubMed with comprehensive strategy (recent RCTs + systematic reviews + relevance)
   * - ALWAYS call Cochrane for systematic reviews
   * - If Scopus API key available: call Scopus
   * - If no Scopus key: additional PubMed search with date sorting as fallback
   */
  async function mandatorySearchNode(state: AgentStateType): Promise<Partial<AgentStateType>> {
    // Extract search query from the last tool call or messages
    let searchQuery = "";

    // Try to find query from previous tool executions (e.g., pico_query_builder result)
    for (const msg of [...state.messages].reverse()) {
      if (msg && typeof msg === "object" && "content" in msg) {
        const content = typeof msg.content === "string" ? msg.content : "";

        // Look for PubMed query in pico_query_builder result
        const pubmedQueryMatch = content.match(/pubmedQuery['":\s]+([^"'}\n]+)/i);
        if (pubmedQueryMatch) {
          searchQuery = pubmedQueryMatch[1].trim();
          break;
        }

        // Fallback: look for any quoted query-like string
        const quotedMatch = content.match(/["']([^"']{20,}(?:AND|OR)[^"']+)["']/);
        if (quotedMatch) {
          searchQuery = quotedMatch[1];
          break;
        }
      }
    }

    // If no query found, construct from PICO/PCC components
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
      console.warn("Mandatory search: No query found, skipping");
      return { phase: "searching" };
    }

    await updateProgress(
      config.researchId,
      "searching",
      45,
      "Running mandatory multi-database search",
      state,
      config.onProgress
    );

    const allResults: unknown[] = [];
    const executions: ToolExecution[] = [];
    const startTime = Date.now();

    // Search 1: PubMed with comprehensive strategy (ALWAYS)
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
      console.error("Mandatory PubMed search failed:", error);
      executions.push({
        tool: "pubmed_search",
        status: "failed",
        query: searchQuery,
        error: error instanceof Error ? error.message : "Unknown error",
        startTime,
      });
    }

    // Search 2: Cochrane (ALWAYS)
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
      console.error("Mandatory Cochrane search failed:", error);
      executions.push({
        tool: "cochrane_search",
        status: "failed",
        query: searchQuery,
        error: error instanceof Error ? error.message : "Unknown error",
        startTime: Date.now(),
      });
    }

    // Search 3: Scopus (IF API KEY AVAILABLE) OR additional PubMed date-sorted search
    if (config.scopusApiKey) {
      try {
        const scopusStartTime = Date.now();

        // Build Scopus-native query (PubMed syntax like [tiab] doesn't work in Scopus)
        // Prefer PICO components when available for best results
        const scopusQuery = config.picoComponents
          ? buildScopusQueryFromPICO(config.picoComponents)
          : convertToScopusQuery(searchQuery);

        // Skip Scopus search if query conversion failed
        if (!scopusQuery) {
          console.warn("Could not build Scopus query, skipping Scopus search");
          throw new Error("Empty Scopus query");
        }

        executions.push({ tool: "scopus_search", status: "running", query: scopusQuery, startTime: scopusStartTime });
        const scopusResult = await scopusSearchTool.invoke({
          query: scopusQuery,
          maxResults: 20,
          apiKey: config.scopusApiKey,
          sortBy: "pubyear", // Sort by recent publications
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
      } catch (error) {
        console.error("Mandatory Scopus search failed:", error);
        executions.push({
          tool: "scopus_search",
          status: "failed",
          query: searchQuery,
          error: error instanceof Error ? error.message : "Unknown error",
          startTime: Date.now(),
        });
      }
    } else {
      // Fallback: Additional PubMed search sorted by date to find recent papers
      try {
        const pubmedDateStartTime = Date.now();
        executions.push({ tool: "pubmed_search_date", status: "running", query: searchQuery, startTime: pubmedDateStartTime });
        const currentYear = new Date().getFullYear();
        const pubmedDateResult = await pubmedSearchTool.invoke({
          query: searchQuery,
          maxResults: 20,
          apiKey: config.ncbiApiKey,
          searchStrategy: "standard",
          dateRange: {
            start: `${currentYear - 2}/01/01`,
            end: `${currentYear}/12/31`,
          },
        });
        const pubmedDateData = JSON.parse(pubmedDateResult);
        if (pubmedDateData.success && pubmedDateData.articles) {
          for (const article of pubmedDateData.articles) {
            // Check for duplicates by PMID
            const isDuplicate = allResults.some(
              (r: unknown) => r && typeof r === "object" && "pmid" in r && (r as { pmid: string }).pmid === article.pmid
            );
            if (!isDuplicate) {
              allResults.push({
                ...article,
                authors: normalizeAuthors(article.authors),
                source: "pubmed",
              });
            }
          }
        }
        executions.push({
          tool: "pubmed_search_date",
          status: "completed",
          query: searchQuery,
          resultCount: pubmedDateData.articles?.length || 0,
          duration: (Date.now() - pubmedDateStartTime) / 1000,
          startTime: pubmedDateStartTime,
        });
      } catch (error) {
        console.error("Additional PubMed date search failed:", error);
      }
    }

    await updateProgress(
      config.researchId,
      "searching",
      55,
      `Found ${allResults.length} articles from mandatory multi-database search`,
      { ...state, toolExecutions: [...(state.toolExecutions || []), ...executions] },
      config.onProgress
    );

    return {
      phase: "searching",
      searchResults: allResults,
      toolExecutions: executions,
    };
  }

  // Minimum results threshold check
  const MIN_SEARCH_RESULTS = 8;

  function shouldContinueAfterMandatorySearch(state: AgentStateType): "agent" | "synthesize" {
    // Check if we have enough results
    if (state.searchResults.length >= MIN_SEARCH_RESULTS) {
      return "synthesize";
    }
    // If not enough, let agent try additional searches
    return "agent";
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

    // Build context with full abstracts and conclusions for grounded synthesis
    const searchResultsContext = state.searchResults
      .filter((r): r is PersistableResult => r !== null && typeof r === "object" && "title" in r)
      .slice(0, 30) // Limit to top 30 for context length
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

## Example of CORRECT vs INCORRECT reporting:

If abstract says: "Beta-blockers did not significantly reduce all-cause death (HR 0.94, 95% CI 0.79-1.12)"

- CORRECT: "The study found no significant reduction in all-cause mortality [n]"
- WRONG: "The study highlighted clinical benefits in reducing mortality [n]" ← HALLUCINATION

## Search Results with FULL Abstracts and Conclusions:
${searchResultsContext}

## Report Structure

IMPORTANT: When citing sources, use numbered in-text citations [1], [2], [3], etc.
Assign reference numbers in order of first citation in the text.
Include a complete "References" section at the end using Vancouver style:

Example Vancouver format:
1. Smith AB, Jones CD. Title of article. Journal Name. 2024;45(3):123-130. doi:10.1000/example

Structure the report with:
1. Executive Summary (MUST accurately reflect the actual findings - if studies show no benefit, say so)
2. Background
3. Methods (search strategy used)
4. Results (organized by evidence level, with [n] citations - quote or closely paraphrase actual findings)
5. Discussion (acknowledge when evidence contradicts expectations)
6. Conclusions (based ONLY on what the evidence actually shows)
7. References (numbered list in Vancouver format)

Focus on:
- ACCURATELY representing study findings, even if negative/null results
- Highlighting recent landmark trials from major journals (NEJM, Lancet, JAMA)
- Noting any conflicting findings between older and newer studies
- Identifying gaps in the literature
- Providing clinical implications based on actual evidence`;

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
    const uniqueRefs = new Set(refMatches);
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
  // Flow: planning -> agent (query building) -> tools -> search -> mandatorySearch -> synthesize OR agent
  const workflow = new StateGraph(AgentState)
    .addNode("planning", planningNode)
    .addNode("agent", agentNode)
    .addNode("tools", toolNodeWithTracking)
    .addNode("search", searchNode)
    .addNode("mandatorySearch", mandatorySearchNode)
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
    .addEdge("search", "mandatorySearch")
    // After mandatory search, decide: synthesize if enough results, else let agent try more
    .addConditionalEdges("mandatorySearch", shouldContinueAfterMandatorySearch, {
      synthesize: "synthesis",
      agent: "agent",
    })
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
