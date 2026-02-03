"""
Hierarchical Progress System

Provides structured progress tracking for deep agent research operations,
including planning steps, agent status, and tool executions.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class StepStatus(str, Enum):
    """Status of a planning step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentState(str, Enum):
    """State of an agent."""
    IDLE = "idle"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolStatus(str, Enum):
    """Status of a tool execution."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanningStep:
    """Represents a step in the research plan."""
    id: str
    name: str
    action: str = ""
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    details: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "status": self.status.value if isinstance(self.status, StepStatus) else self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "error": self.error,
        }


@dataclass
class AgentStatus:
    """Represents the status of an agent."""
    name: str
    status: AgentState = AgentState.IDLE
    current_tool: Optional[str] = None
    current_step: Optional[str] = None
    parent_agent: Optional[str] = None
    started_at: Optional[datetime] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value if isinstance(self.status, AgentState) else self.status,
            "current_tool": self.current_tool,
            "current_step": self.current_step,
            "parent_agent": self.parent_agent,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "message": self.message,
        }


@dataclass
class ToolExecution:
    """Represents a tool execution."""
    tool: str
    status: str = "running"
    query: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    result_preview: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "tool": self.tool,
            "status": self.status,
            "query": self.query[:100] + "..." if self.query and len(self.query) > 100 else self.query,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "result_preview": self.result_preview,
            "error": self.error,
        }


@dataclass
class ProgressState:
    """Complete progress state for a research session."""
    research_id: str
    phase: str = "init"
    message: str = "Initializing..."
    overall_progress: int = 0
    planning_steps: List[PlanningStep] = field(default_factory=list)
    active_agents: List[AgentStatus] = field(default_factory=list)
    tool_executions: List[ToolExecution] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "research_id": self.research_id,
            "phase": self.phase,
            "message": self.message,
            "overall_progress": self.overall_progress,
            "planning_steps": [step.to_dict() for step in self.planning_steps],
            "active_agents": [agent.to_dict() for agent in self.active_agents],
            "tool_executions": [exec.to_dict() for exec in self.tool_executions],
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class HierarchicalProgressManager:
    """
    Manages hierarchical progress tracking for deep agent research.

    Tracks planning steps, agent status, and tool executions, providing
    real-time updates via callbacks for UI display.
    """

    def __init__(self, research_id: str):
        """
        Initialize the progress manager.

        Args:
            research_id: Unique identifier for this research session
        """
        self.research_id = research_id
        self.state = ProgressState(research_id=research_id)
        self._callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._step_start_times: Dict[str, float] = {}
        self._tool_start_times: Dict[str, float] = {}

        # Initialize main agent
        self.state.active_agents.append(
            AgentStatus(
                name="main",
                status=AgentState.IDLE,
                started_at=datetime.now(UTC)
            )
        )

        logger.info(f"Initialized HierarchicalProgressManager for research {research_id}")

    def set_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set the callback function for progress updates."""
        self._callback = callback

    def _emit_update(self) -> None:
        """Emit a progress update via the callback."""
        self.state.updated_at = datetime.now(UTC)

        if self._callback:
            try:
                self._callback(self.state.to_dict())
            except Exception as e:
                logger.exception(f"Error in progress callback: {e}")

    # Phase Management
    def update_phase(self, phase: str, message: str, progress: Optional[int] = None) -> None:
        """
        Update the current phase.

        Args:
            phase: Phase identifier (init, planning, execution, synthesis, etc.)
            message: Human-readable phase message
            progress: Optional progress percentage (0-100)
        """
        self.state.phase = phase
        self.state.message = message
        if progress is not None:
            self.state.overall_progress = progress

        # Update main agent status
        main_agent = self._get_main_agent()
        if main_agent:
            main_agent.message = message
            if phase == "planning":
                main_agent.status = AgentState.PLANNING
            elif phase in ["execution", "synthesis"]:
                main_agent.status = AgentState.RUNNING
            elif phase == "complete":
                main_agent.status = AgentState.COMPLETED

        logger.info(f"Phase updated: {phase} - {message}")
        self._emit_update()

    def update_progress(self, progress: int, message: Optional[str] = None) -> None:
        """
        Update overall progress.

        Args:
            progress: Progress percentage (0-100)
            message: Optional status message
        """
        self.state.overall_progress = min(100, max(0, progress))
        if message:
            self.state.message = message
        self._emit_update()

    # Planning Step Management
    def add_planning_step(self, step: PlanningStep) -> None:
        """
        Add a planning step.

        Args:
            step: The planning step to add
        """
        self.state.planning_steps.append(step)
        logger.debug(f"Added planning step: {step.name}")
        self._emit_update()

    def update_step_status(
        self,
        step_id: str,
        status: str,
        details: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Update a planning step's status.

        Args:
            step_id: ID of the step to update
            status: New status (pending, in_progress, completed, failed, skipped)
            details: Optional details about the step
            error: Optional error message if failed
        """
        step = self.get_step(step_id)
        if not step:
            return

        # Convert string to enum if needed
        try:
            step.status = StepStatus(status) if isinstance(status, str) else status
        except ValueError:
            step.status = status

        if status == "in_progress":
            step.started_at = datetime.now(UTC)
            self._step_start_times[step_id] = time.time()
        elif status in ["completed", "failed"]:
            step.completed_at = datetime.now(UTC)
            if step_id in self._step_start_times:
                elapsed = time.time() - self._step_start_times[step_id]
                step.duration_ms = int(elapsed * 1000)

        if details:
            step.details = details
        if error:
            step.error = error

        logger.debug(f"Step {step_id} status updated to {status}")
        self._emit_update()

    def get_step(self, step_id: str) -> Optional[PlanningStep]:
        """Get a planning step by ID."""
        for step in self.state.planning_steps:
            if step.id == step_id:
                return step
        return None

    def get_completed_steps(self) -> List[PlanningStep]:
        """Get all completed steps."""
        return [
            step for step in self.state.planning_steps
            if step.status == StepStatus.COMPLETED
        ]

    def get_pending_steps(self) -> List[PlanningStep]:
        """Get all pending steps."""
        return [
            step for step in self.state.planning_steps
            if step.status == StepStatus.PENDING
        ]

    # Agent Management
    def _get_main_agent(self) -> Optional[AgentStatus]:
        """Get the main agent status."""
        return next(
            (a for a in self.state.active_agents if a.name == "main"),
            None
        )

    def update_agent_status(
        self,
        agent_name: str,
        status: str,
        current_tool: Optional[str] = None,
        current_step: Optional[str] = None,
        message: Optional[str] = None
    ) -> None:
        """
        Update an agent's status.

        Args:
            agent_name: Name of the agent
            status: New status
            current_tool: Tool currently being used
            current_step: Step currently being executed
            message: Status message
        """
        # Find existing agent or create new one
        agent = next(
            (a for a in self.state.active_agents if a.name == agent_name),
            None
        )

        if not agent:
            agent = AgentStatus(name=agent_name, started_at=datetime.now(UTC))
            self.state.active_agents.append(agent)

        # Convert string to enum if needed
        try:
            agent.status = AgentState(status) if isinstance(status, str) else status
        except ValueError:
            agent.status = status

        if current_tool is not None:
            agent.current_tool = current_tool
        if current_step is not None:
            agent.current_step = current_step
        if message is not None:
            agent.message = message

        logger.debug(f"Agent {agent_name} status updated to {status}")
        self._emit_update()

    def add_sub_agent(self, name: str, parent: str = "main") -> None:
        """
        Add a sub-agent.

        Args:
            name: Name of the sub-agent
            parent: Name of the parent agent
        """
        agent = AgentStatus(
            name=name,
            parent_agent=parent,
            started_at=datetime.now(UTC)
        )
        self.state.active_agents.append(agent)
        logger.debug(f"Added sub-agent: {name} (parent: {parent})")
        self._emit_update()

    def remove_sub_agent(self, name: str) -> None:
        """Remove a sub-agent."""
        self.state.active_agents = [
            a for a in self.state.active_agents if a.name != name
        ]
        self._emit_update()

    # Tool Execution Management
    def add_tool_execution(self, execution: ToolExecution) -> None:
        """
        Add a tool execution record.

        Args:
            execution: The tool execution to record
        """
        self.state.tool_executions.append(execution)
        self._tool_start_times[execution.tool] = time.time()

        # Update main agent's current tool
        main_agent = self._get_main_agent()
        if main_agent:
            main_agent.current_tool = execution.tool

        logger.debug(f"Tool execution started: {execution.tool}")
        self._emit_update()

    def update_tool_execution(self, execution: ToolExecution) -> None:
        """
        Update a tool execution record.

        Args:
            execution: The updated tool execution
        """
        # Find and update the existing execution
        for i, exec in enumerate(self.state.tool_executions):
            if exec.tool == execution.tool and exec.started_at == execution.started_at:
                # Calculate duration if completed
                if execution.status in ["completed", "failed"]:
                    execution.completed_at = datetime.now(UTC)
                    if execution.tool in self._tool_start_times:
                        execution.duration_ms = int(
                            (time.time() - self._tool_start_times[execution.tool]) * 1000
                        )

                self.state.tool_executions[i] = execution
                break

        # Clear main agent's current tool if completed
        if execution.status in ["completed", "failed"]:
            main_agent = self._get_main_agent()
            if main_agent and main_agent.current_tool == execution.tool:
                main_agent.current_tool = None

        logger.debug(f"Tool execution updated: {execution.tool} -> {execution.status}")
        self._emit_update()

    def get_tool_executions(self, tool: Optional[str] = None) -> List[ToolExecution]:
        """
        Get tool executions, optionally filtered by tool name.

        Args:
            tool: Optional tool name to filter by

        Returns:
            List of matching tool executions
        """
        if tool:
            return [e for e in self.state.tool_executions if e.tool == tool]
        return self.state.tool_executions

    def get_recent_tool_executions(self, limit: int = 10) -> List[ToolExecution]:
        """Get the most recent tool executions."""
        return self.state.tool_executions[-limit:]

    # Progress Calculation
    def calculate_overall_progress(self) -> int:
        """
        Calculate overall progress based on completed steps.

        Returns:
            Progress percentage (0-100)
        """
        if not self.state.planning_steps:
            return self.state.overall_progress

        total_steps = len(self.state.planning_steps)
        completed_steps = len([
            s for s in self.state.planning_steps
            if s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED]
        ])
        in_progress_steps = len([
            s for s in self.state.planning_steps
            if s.status == StepStatus.IN_PROGRESS
        ])

        # Base progress from completed steps
        base_progress = (completed_steps / total_steps) * 100

        # Add partial progress for in-progress steps (assume 50% done)
        partial_progress = (in_progress_steps * 0.5 / total_steps) * 100

        return min(100, int(base_progress + partial_progress))

    # State Export
    def get_state(self) -> Dict[str, Any]:
        """Get the complete progress state as a dictionary."""
        return self.state.to_dict()

    def get_summary(self) -> str:
        """Get a text summary of current progress."""
        completed = len(self.get_completed_steps())
        total = len(self.state.planning_steps)
        recent_tools = self.get_recent_tool_executions(3)

        summary = f"Progress: {self.state.overall_progress}% | "
        summary += f"Steps: {completed}/{total} | "
        summary += f"Phase: {self.state.phase}"

        if recent_tools:
            tools_str = ", ".join(t.tool for t in recent_tools)
            summary += f" | Recent tools: {tools_str}"

        return summary
