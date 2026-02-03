"""
Deep Agent Research System

Replaces the strategy-based AdvancedSearchSystem with a LangChain Deep Agent architecture
that provides autonomous planning, tool execution, and hierarchical progress reporting.
"""

import uuid
from typing import Any, Callable, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from loguru import logger

from .progress.hierarchical_progress import (
    HierarchicalProgressManager,
    PlanningStep,
    ToolExecution,
)
from .tools.medical_tools import (
    create_citation_formatter_tool,
    create_evidence_classifier_tool,
    create_mesh_term_mapping_tool,
    create_pico_query_builder_tool,
    create_pubmed_search_tool,
)
from .web_search_engines.search_engine_base import BaseSearchEngine


# Medical research system prompt
MEDICAL_RESEARCH_SYSTEM_PROMPT = """You are a medical research assistant specialized in evidence-based medicine.

Your role is to help researchers find and synthesize high-quality medical evidence using the PICO framework:
- P (Population): Patient or problem characteristics
- I (Intervention): Treatment, diagnostic test, or exposure
- C (Comparison): Alternative intervention or control
- O (Outcome): Clinical outcomes of interest

Evidence Hierarchy (prioritize higher levels):
- Level I: Systematic reviews and meta-analyses of RCTs
- Level II: Randomized controlled trials (RCTs)
- Level III: Cohort studies (prospective/retrospective)
- Level IV: Case-control studies
- Level V: Case reports, expert opinion

Research Guidelines:
1. Always start by breaking down the research question using PICO
2. Use MeSH terms for precise PubMed searches
3. Prioritize systematic reviews and RCTs when available
4. Classify evidence levels for all cited studies
5. Acknowledge limitations and potential biases
6. Format citations properly for medical literature

Available Tools:
- pico_query_builder: Build structured PICO queries
- mesh_term_mapping: Map common terms to MeSH vocabulary
- pubmed_search: Search PubMed with MeSH terms
- evidence_classifier: Classify study evidence levels
- citation_formatter: Format medical citations

When conducting research:
1. Plan your approach by listing steps as TODOs
2. Execute each step methodically
3. Synthesize findings with proper evidence attribution
4. Provide actionable conclusions for clinicians/researchers
"""


class DeepAgentResearchSystem:
    """
    Deep Agent Research System using LangChain agents for autonomous medical research.

    This system replaces the strategy-based approach with a more flexible agent
    that can autonomously plan, execute tools, and synthesize findings.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        search: BaseSearchEngine,
        max_iterations: int = 10,
        enable_sub_agents: bool = True,
        username: str | None = None,
        settings_snapshot: dict | None = None,
        research_id: str | None = None,
        research_context: dict | None = None,
    ):
        """
        Initialize the Deep Agent Research System.

        Args:
            llm: The language model to use for the agent
            search: Search engine instance for PubMed queries
            max_iterations: Maximum agent iterations before stopping
            enable_sub_agents: Whether to allow spawning sub-agents for complex tasks
            username: Username for tracking
            settings_snapshot: Settings snapshot for configuration
            research_id: Research session ID
            research_context: Additional context for the research
        """
        self.model = llm
        self.search = search
        self.max_iterations = max_iterations
        self.enable_sub_agents = enable_sub_agents
        self.username = username
        self.settings_snapshot = settings_snapshot or {}
        self.research_id = research_id or str(uuid.uuid4())
        self.research_context = research_context or {}

        # Initialize progress manager
        self.progress_manager = HierarchicalProgressManager(
            research_id=self.research_id
        )

        # Progress callback for external updates
        self.progress_callback: Callable[[str, int, dict], None] = lambda m, p, d: None

        # Initialize tools
        self.tools = self._create_tools()

        # Track all links for citation management
        self.all_links_of_system: List[Dict[str, Any]] = []

        # Questions by iteration for compatibility
        self.questions_by_iteration: List[Any] = []

        logger.info(
            f"Initialized DeepAgentResearchSystem with {len(self.tools)} tools, "
            f"max_iterations={max_iterations}, research_id={self.research_id}"
        )

    def _create_tools(self) -> List[BaseTool]:
        """Create the medical research tools."""
        tools = [
            create_pico_query_builder_tool(self.model),
            create_mesh_term_mapping_tool(),
            create_pubmed_search_tool(self.search, self.model),
            create_evidence_classifier_tool(),
            create_citation_formatter_tool(),
        ]
        return tools

    def set_progress_callback(
        self, callback: Callable[[str, int, dict], None]
    ) -> None:
        """Set a callback function to receive progress updates."""
        self.progress_callback = callback
        self.progress_manager.set_callback(self._on_progress_update)

    def _on_progress_update(self, progress_data: dict) -> None:
        """Handle progress updates from the progress manager."""
        message = progress_data.get("message", "Processing...")
        progress = progress_data.get("overall_progress", 0)

        # Build metadata including hierarchical progress info
        metadata = {
            "phase": progress_data.get("phase", "processing"),
            "planning_steps": [
                step.to_dict() for step in progress_data.get("planning_steps", [])
            ],
            "active_agents": progress_data.get("active_agents", []),
            "tool_executions": [
                exec.to_dict() for exec in progress_data.get("tool_executions", [])
            ],
            "hierarchical_progress": True,
        }

        self.progress_callback(message, progress, metadata)

    def analyze_topic(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        Analyze a medical research topic using the deep agent.

        Args:
            query: The research query to analyze
            **kwargs: Additional arguments

        Returns:
            Dictionary containing research results
        """
        logger.info(f"Starting deep agent analysis for query: {query}")

        # Send initial progress
        self.progress_callback(
            "Initializing deep agent research system",
            5,
            {"phase": "init", "hierarchical_progress": True}
        )

        try:
            # Phase 1: Planning
            self._emit_phase("planning", "Creating research plan", 10)
            planning_steps = self._create_research_plan(query)

            # Phase 2: Execute plan
            self._emit_phase("execution", "Executing research plan", 20)
            findings = self._execute_research_plan(query, planning_steps)

            # Phase 3: Synthesize
            self._emit_phase("synthesis", "Synthesizing findings", 80)
            synthesis = self._synthesize_findings(query, findings)

            # Phase 4: Format output
            self._emit_phase("formatting", "Formatting results", 95)
            result = self._format_results(query, findings, synthesis)

            self.progress_callback(
                "Research completed successfully",
                100,
                {"phase": "complete", "hierarchical_progress": True}
            )

            return result

        except Exception as e:
            logger.exception(f"Error in deep agent analysis: {e}")
            self.progress_callback(
                f"Research failed: {str(e)}",
                0,
                {"phase": "error", "error": str(e)}
            )
            raise

    def _emit_phase(self, phase: str, message: str, progress: int) -> None:
        """Emit a phase update."""
        self.progress_manager.update_phase(phase, message)
        self.progress_callback(
            message,
            progress,
            {"phase": phase, "hierarchical_progress": True}
        )

    def _create_research_plan(self, query: str) -> List[PlanningStep]:
        """
        Create a research plan by having the LLM break down the query.

        Args:
            query: The research query

        Returns:
            List of planning steps
        """
        logger.info("Creating research plan...")

        # Ask LLM to create a plan
        planning_prompt = f"""Break down this medical research query into a step-by-step plan.

Research Query: {query}

Create 3-6 concrete steps to answer this query. Each step should use one of these approaches:
1. Build PICO query - Structure the question using PICO framework
2. Map MeSH terms - Convert common terms to MeSH vocabulary
3. Search PubMed - Search for evidence on specific aspects
4. Classify evidence - Evaluate the quality of found studies
5. Synthesize findings - Combine results into conclusions

Format each step as:
STEP [number]: [brief description]
ACTION: [pico_query | mesh_mapping | pubmed_search | evidence_classification | synthesis]

Example:
STEP 1: Structure the research question using PICO
ACTION: pico_query

STEP 2: Map key terms to MeSH vocabulary
ACTION: mesh_mapping

Provide your plan:
"""

        try:
            response = self.model.invoke([
                SystemMessage(content=MEDICAL_RESEARCH_SYSTEM_PROMPT),
                HumanMessage(content=planning_prompt)
            ])

            plan_text = response.content if hasattr(response, 'content') else str(response)
            steps = self._parse_plan(plan_text)

            # Register steps with progress manager
            for step in steps:
                self.progress_manager.add_planning_step(step)

            logger.info(f"Created research plan with {len(steps)} steps")
            return steps

        except Exception as e:
            logger.exception(f"Error creating research plan: {e}")
            # Return a default plan
            default_steps = [
                PlanningStep(id="1", name="Build PICO query", action="pico_query"),
                PlanningStep(id="2", name="Search PubMed", action="pubmed_search"),
                PlanningStep(id="3", name="Classify evidence", action="evidence_classification"),
                PlanningStep(id="4", name="Synthesize findings", action="synthesis"),
            ]
            for step in default_steps:
                self.progress_manager.add_planning_step(step)
            return default_steps

    def _parse_plan(self, plan_text: str) -> List[PlanningStep]:
        """Parse the LLM's plan into PlanningStep objects."""
        steps = []
        current_step = None
        step_id = 0

        for line in plan_text.strip().split('\n'):
            line = line.strip()
            if line.startswith('STEP'):
                step_id += 1
                # Extract step name
                parts = line.split(':', 1)
                name = parts[1].strip() if len(parts) > 1 else f"Step {step_id}"
                current_step = {"id": str(step_id), "name": name, "action": "unknown"}
            elif line.startswith('ACTION:') and current_step:
                action = line.replace('ACTION:', '').strip().lower()
                current_step["action"] = action
                steps.append(PlanningStep(**current_step))
                current_step = None

        # Handle any remaining step
        if current_step:
            steps.append(PlanningStep(**current_step))

        return steps if steps else [
            PlanningStep(id="1", name="Analyze query", action="pubmed_search")
        ]

    def _execute_research_plan(
        self, query: str, steps: List[PlanningStep]
    ) -> List[Dict[str, Any]]:
        """
        Execute the research plan step by step.

        Args:
            query: Original research query
            steps: Planning steps to execute

        Returns:
            List of findings from each step
        """
        findings = []
        accumulated_context = f"Original Query: {query}\n\n"

        for i, step in enumerate(steps):
            step_progress = 20 + int((i / len(steps)) * 60)  # Progress from 20-80%

            self.progress_manager.update_step_status(step.id, "in_progress")
            self.progress_callback(
                f"Executing: {step.name}",
                step_progress,
                {
                    "phase": "execution",
                    "current_step": step.to_dict(),
                    "hierarchical_progress": True
                }
            )

            try:
                # Execute the step based on its action
                result = self._execute_step(step, query, accumulated_context)

                if result:
                    findings.append({
                        "step_id": step.id,
                        "step_name": step.name,
                        "action": step.action,
                        "content": result.get("content", ""),
                        "sources": result.get("sources", []),
                        "evidence_levels": result.get("evidence_levels", {}),
                    })

                    # Add to accumulated context for next steps
                    accumulated_context += f"\n## {step.name}\n{result.get('content', '')}\n"

                    # Track sources
                    if result.get("sources"):
                        self.all_links_of_system.extend(result["sources"])

                self.progress_manager.update_step_status(step.id, "completed")

            except Exception as e:
                logger.exception(f"Error executing step {step.name}: {e}")
                self.progress_manager.update_step_status(step.id, "failed")
                findings.append({
                    "step_id": step.id,
                    "step_name": step.name,
                    "action": step.action,
                    "content": f"Error: {str(e)}",
                    "sources": [],
                    "error": str(e),
                })

        return findings

    def _execute_step(
        self, step: PlanningStep, query: str, context: str
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a single planning step.

        Args:
            step: The step to execute
            query: Original query
            context: Accumulated context from previous steps

        Returns:
            Step result with content and sources
        """
        action = step.action.lower()

        # Start tool execution tracking
        tool_exec = ToolExecution(
            tool=action,
            status="running",
            query=query[:100] if len(query) > 100 else query
        )
        self.progress_manager.add_tool_execution(tool_exec)

        # Map actions to their handler methods
        action_handlers = {
            "pico_query": self._execute_pico_query,
            "pico": self._execute_pico_query,
            "mesh_mapping": self._execute_mesh_mapping,
            "mesh": self._execute_mesh_mapping,
            "pubmed_search": self._execute_pubmed_search,
            "search": self._execute_pubmed_search,
            "pubmed": self._execute_pubmed_search,
            "evidence_classification": self._execute_evidence_classification,
            "evidence": self._execute_evidence_classification,
            "classify": self._execute_evidence_classification,
            "synthesis": self._execute_synthesis,
            "synthesize": self._execute_synthesis,
        }

        try:
            handler = action_handlers.get(action, self._execute_pubmed_search)

            # Evidence classification only needs context
            if action in ["evidence_classification", "evidence", "classify"]:
                result = handler(context)
            else:
                result = handler(query, context)

            tool_exec.status = "completed"
            self.progress_manager.update_tool_execution(tool_exec)
            return result

        except Exception as e:
            tool_exec.status = "failed"
            tool_exec.error = str(e)
            self.progress_manager.update_tool_execution(tool_exec)
            raise

    def _get_tool(self, name_fragment: str) -> Optional[BaseTool]:
        """Get a tool by name fragment."""
        for tool in self.tools:
            if name_fragment in tool.name.lower():
                return tool
        return None

    def _execute_pico_query(self, query: str, context: str) -> Dict[str, Any]:
        """Execute PICO query building."""
        pico_tool = self._get_tool("pico")

        if pico_tool:
            try:
                result = pico_tool.invoke({"query": query})
                return {"content": result, "sources": []}
            except Exception as e:
                logger.warning(f"PICO tool failed: {e}, using LLM fallback")

        # Fallback to direct LLM call
        prompt = f"""Analyze this medical research query using the PICO framework:

Query: {query}

Provide:
P (Population): Who are the patients/subjects?
I (Intervention): What treatment/exposure is being studied?
C (Comparison): What is the comparison/control?
O (Outcome): What outcomes are being measured?

Also suggest optimized search terms for PubMed.
"""
        response = self.model.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, 'content') else str(response)
        return {"content": content, "sources": []}

    def _execute_mesh_mapping(self, query: str, context: str) -> Dict[str, Any]:
        """Execute MeSH term mapping."""
        mesh_tool = self._get_tool("mesh")

        if mesh_tool:
            try:
                result = mesh_tool.invoke({"terms": query})
                return {"content": result, "sources": []}
            except Exception as e:
                logger.warning(f"MeSH tool failed: {e}")

        return {"content": f"MeSH mapping for: {query}", "sources": []}

    def _execute_pubmed_search(self, query: str, context: str) -> Dict[str, Any]:
        """Execute PubMed search."""
        pubmed_tool = self._get_tool("pubmed")

        if pubmed_tool:
            try:
                result = pubmed_tool.invoke({"query": query})
                sources = self._extract_sources_from_search(result)
                return {"content": result, "sources": sources}
            except Exception as e:
                logger.warning(f"PubMed tool failed: {e}")

        # Fallback to direct search engine call
        if self.search:
            try:
                results = self.search.run(query)
                content = self._format_search_results(results)
                sources = [
                    {"title": r.get("title", ""), "link": r.get("link", "")}
                    for r in results if isinstance(r, dict)
                ]
                return {"content": content, "sources": sources}
            except Exception as e:
                logger.exception(f"Direct search failed: {e}")

        return {"content": "No search results available", "sources": []}

    def _execute_evidence_classification(self, context: str) -> Dict[str, Any]:
        """Execute evidence classification on accumulated findings."""
        evidence_tool = self._get_tool("evidence")

        if evidence_tool:
            try:
                result = evidence_tool.invoke({"text": context})
                return {"content": result, "sources": [], "evidence_levels": {}}
            except Exception as e:
                logger.warning(f"Evidence tool failed: {e}")

        # LLM fallback for classification
        prompt = f"""Classify the evidence levels of studies mentioned in this research context:

{context}

For each study or finding, identify:
- Study type (RCT, cohort, case-control, etc.)
- Evidence level (I-V)
- Key limitations

Format as a structured summary.
"""
        response = self.model.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, 'content') else str(response)
        return {"content": content, "sources": [], "evidence_levels": {}}

    def _execute_synthesis(self, query: str, context: str) -> Dict[str, Any]:
        """Execute synthesis of findings."""
        prompt = f"""Synthesize the following medical research findings to answer the original query.

Original Query: {query}

Research Findings:
{context}

Provide a comprehensive synthesis that:
1. Directly answers the research question
2. Weighs evidence by quality level
3. Acknowledges limitations and gaps
4. Suggests clinical/research implications
5. Identifies areas needing further research

Format with clear sections and proper citations.
"""
        response = self.model.invoke([
            SystemMessage(content=MEDICAL_RESEARCH_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ])
        content = response.content if hasattr(response, 'content') else str(response)
        return {"content": content, "sources": []}

    def _synthesize_findings(
        self, query: str, findings: List[Dict[str, Any]]
    ) -> str:
        """
        Create final synthesis from all findings.

        Args:
            query: Original query
            findings: All findings from plan execution

        Returns:
            Synthesized research summary
        """
        # Combine all finding content
        combined_content = "\n\n".join([
            f"## {f['step_name']}\n{f['content']}"
            for f in findings if f.get('content')
        ])

        # Generate final synthesis
        result = self._execute_synthesis(query, combined_content)
        return result.get("content", "Unable to synthesize findings")

    def _format_results(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        synthesis: str
    ) -> Dict[str, Any]:
        """
        Format the final research results.

        Args:
            query: Original query
            findings: All findings
            synthesis: Synthesized summary

        Returns:
            Formatted result dictionary
        """
        # Collect all sources
        all_sources = []
        for finding in findings:
            all_sources.extend(finding.get("sources", []))

        # Build formatted findings output
        formatted_findings = f"""# Research Report: {query}

## Executive Summary
{synthesis}

## Detailed Findings
"""
        for finding in findings:
            if finding.get("content") and not finding.get("error"):
                formatted_findings += f"\n### {finding['step_name']}\n{finding['content']}\n"

        # Add sources section
        if all_sources:
            formatted_findings += "\n## Sources\n"
            for i, source in enumerate(all_sources[:20], 1):  # Limit to 20 sources
                title = source.get("title", "Unknown")
                link = source.get("link", "")
                formatted_findings += f"{i}. [{title}]({link})\n"

        return {
            "query": query,
            "findings": findings,
            "formatted_findings": formatted_findings,
            "current_knowledge": synthesis,
            "iterations": len(findings),
            "all_links_of_system": self.all_links_of_system,
            "questions_by_iteration": self.questions_by_iteration,
            "search_system": self,
        }

    def _extract_sources_from_search(self, result: str) -> List[Dict[str, Any]]:
        """Extract source information from search result text."""
        # Simple extraction - in practice would parse structured results
        sources = []
        # This would be enhanced based on actual result format
        return sources

    def _format_search_results(self, results: List[Dict[str, Any]]) -> str:
        """Format search results into readable text."""
        if not results:
            return "No results found."

        formatted = []
        for r in results[:10]:  # Limit to 10 results
            if isinstance(r, dict):
                title = r.get("title", "Unknown")
                snippet = r.get("snippet", r.get("content", ""))[:300]
                link = r.get("link", "")
                formatted.append(f"**{title}**\n{snippet}\nSource: {link}\n")

        return "\n\n".join(formatted) if formatted else "No results found."
