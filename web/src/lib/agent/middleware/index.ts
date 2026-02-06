/**
 * Middleware exports for Medical Deep Research DeepAgents integration
 *
 * This module exports all middleware components for configuring the agent:
 * - Todo management for dynamic task tracking
 * - Filesystem tools for context offloading
 * - Subagent delegation for specialized tasks
 */

// Todo middleware
export {
  createWriteTodosTool,
  getResearchTodos,
  updateTodoStatus,
  type TodoItem,
} from "./todo-middleware";

// Filesystem middleware
export {
  createFilesystemTools,
  createLsTool,
  createReadFileTool,
  createWriteFileTool,
  createEditFileTool,
} from "./filesystem-middleware";

// Subagent middleware
export {
  createTaskTool,
  getSubagentExecutions,
  SUBAGENT_DEFINITIONS,
  type SubagentType,
  type SubagentConfig,
} from "./subagent-middleware";
