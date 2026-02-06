/**
 * Filesystem Middleware for Medical Deep Research
 *
 * Implements filesystem tools for context offloading to prevent overflow.
 * Storage: data/research/{researchId}/ directory
 *
 * Tools:
 * - ls: List files in research directory
 * - read_file: Read stored content
 * - write_file: Store large results (>20 articles)
 * - edit_file: Modify files
 */

import { DynamicStructuredTool } from "@langchain/core/tools";
import { z } from "zod";
import { db } from "@/db";
import { researchFiles } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { generateId } from "@/lib/utils";
import * as fs from "fs/promises";
import * as path from "path";

// Base directory for research files
const getResearchDir = (researchId: string) =>
  path.join(process.cwd(), "data", "research", researchId);

/**
 * Create ls tool for listing files in research directory
 */
export function createLsTool(researchId: string): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "ls",
    description: "List files in the research directory. Use to see what files have been stored.",
    schema: z.object({
      path: z.string().optional().default("/").describe("Relative path within research directory"),
    }),
    func: async ({ path: relativePath }: { path: string }) => {
      try {
        const baseDir = getResearchDir(researchId);
        const targetPath = path.join(baseDir, relativePath);

        // Ensure target is within research directory
        if (!targetPath.startsWith(baseDir)) {
          return JSON.stringify({ error: "Path outside research directory" });
        }

        // Check if directory exists
        try {
          await fs.access(targetPath);
        } catch {
          // Directory doesn't exist, return empty list
          return JSON.stringify({
            path: relativePath,
            files: [],
            directories: [],
          });
        }

        const entries = await fs.readdir(targetPath, { withFileTypes: true });

        const files = entries
          .filter(e => e.isFile())
          .map(e => ({
            name: e.name,
            path: path.join(relativePath, e.name),
          }));

        const directories = entries
          .filter(e => e.isDirectory())
          .map(e => ({
            name: e.name,
            path: path.join(relativePath, e.name) + "/",
          }));

        return JSON.stringify({
          path: relativePath,
          files,
          directories,
        });
      } catch (error) {
        return JSON.stringify({
          error: error instanceof Error ? error.message : "Failed to list files",
        });
      }
    },
  });
}

/**
 * Create read_file tool for reading stored content
 */
export function createReadFileTool(researchId: string): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "read_file",
    description: "Read content from a file in the research directory.",
    schema: z.object({
      file_path: z.string().describe("Relative path to the file"),
      offset: z.number().optional().default(0).describe("Line offset to start reading from (0-indexed)"),
      limit: z.number().optional().default(500).describe("Maximum number of lines to read"),
    }),
    func: async ({ file_path, offset, limit }: { file_path: string; offset: number; limit: number }) => {
      try {
        const baseDir = getResearchDir(researchId);
        const targetPath = path.join(baseDir, file_path);

        // Ensure target is within research directory
        if (!targetPath.startsWith(baseDir)) {
          return JSON.stringify({ error: "Path outside research directory" });
        }

        const content = await fs.readFile(targetPath, "utf-8");
        const lines = content.split("\n");
        const selectedLines = lines.slice(offset, offset + limit);

        // Format with line numbers
        const formatted = selectedLines
          .map((line, i) => `${(offset + i + 1).toString().padStart(4)}| ${line}`)
          .join("\n");

        return JSON.stringify({
          path: file_path,
          content: formatted,
          totalLines: lines.length,
          linesShown: selectedLines.length,
          offset,
        });
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") {
          return JSON.stringify({ error: `File not found: ${file_path}` });
        }
        return JSON.stringify({
          error: error instanceof Error ? error.message : "Failed to read file",
        });
      }
    },
  });
}

/**
 * Create write_file tool for storing large results
 */
export function createWriteFileTool(researchId: string): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "write_file",
    description: `Write content to a file in the research directory.
Use this to offload large search results (>20 articles) from context.

Example usage:
- write_file("search_results/pubmed.json", JSON.stringify(results))
- write_file("synthesis/draft.md", reportContent)`,
    schema: z.object({
      file_path: z.string().describe("Relative path for the file"),
      content: z.string().describe("Content to write"),
    }),
    func: async ({ file_path, content }: { file_path: string; content: string }) => {
      try {
        const baseDir = getResearchDir(researchId);
        const targetPath = path.join(baseDir, file_path);

        // Ensure target is within research directory
        if (!targetPath.startsWith(baseDir)) {
          return JSON.stringify({ error: "Path outside research directory" });
        }

        // Create parent directories if needed
        await fs.mkdir(path.dirname(targetPath), { recursive: true });

        // Write file
        await fs.writeFile(targetPath, content, "utf-8");

        // Track in database
        const now = new Date();
        const existingFile = await db.query.researchFiles.findFirst({
          where: and(
            eq(researchFiles.researchId, researchId),
            eq(researchFiles.path, file_path)
          ),
        });

        if (existingFile) {
          await db
            .update(researchFiles)
            .set({
              content: content.length > 10000 ? content.substring(0, 10000) + "..." : content,
              size: content.length,
              updatedAt: now,
            })
            .where(eq(researchFiles.id, existingFile.id));
        } else {
          await db.insert(researchFiles).values({
            id: generateId(),
            researchId,
            path: file_path,
            content: content.length > 10000 ? content.substring(0, 10000) + "..." : content,
            size: content.length,
            createdAt: now,
            updatedAt: now,
          });
        }

        return JSON.stringify({
          success: true,
          path: file_path,
          size: content.length,
          message: `Wrote ${content.length} bytes to ${file_path}`,
        });
      } catch (error) {
        return JSON.stringify({
          error: error instanceof Error ? error.message : "Failed to write file",
        });
      }
    },
  });
}

/**
 * Create edit_file tool for modifying files
 */
export function createEditFileTool(researchId: string): DynamicStructuredTool {
  return new DynamicStructuredTool({
    name: "edit_file",
    description: "Edit a file by replacing a string with another string.",
    schema: z.object({
      file_path: z.string().describe("Relative path to the file"),
      old_string: z.string().describe("String to find and replace"),
      new_string: z.string().describe("Replacement string"),
      replace_all: z.boolean().optional().default(false).describe("Replace all occurrences"),
    }),
    func: async ({
      file_path,
      old_string,
      new_string,
      replace_all,
    }: {
      file_path: string;
      old_string: string;
      new_string: string;
      replace_all: boolean;
    }) => {
      try {
        const baseDir = getResearchDir(researchId);
        const targetPath = path.join(baseDir, file_path);

        // Ensure target is within research directory
        if (!targetPath.startsWith(baseDir)) {
          return JSON.stringify({ error: "Path outside research directory" });
        }

        // Read existing content
        let content: string;
        try {
          content = await fs.readFile(targetPath, "utf-8");
        } catch {
          return JSON.stringify({ error: `File not found: ${file_path}` });
        }

        // Check if old_string exists
        if (!content.includes(old_string)) {
          return JSON.stringify({
            error: `String not found in file: "${old_string.substring(0, 50)}..."`,
          });
        }

        // Replace
        let newContent: string;
        let occurrences: number;

        if (replace_all) {
          occurrences = (content.match(new RegExp(old_string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;
          newContent = content.replaceAll(old_string, new_string);
        } else {
          occurrences = 1;
          newContent = content.replace(old_string, new_string);
        }

        // Write back
        await fs.writeFile(targetPath, newContent, "utf-8");

        // Update database
        const now = new Date();
        await db
          .update(researchFiles)
          .set({
            content: newContent.length > 10000 ? newContent.substring(0, 10000) + "..." : newContent,
            size: newContent.length,
            updatedAt: now,
          })
          .where(
            and(
              eq(researchFiles.researchId, researchId),
              eq(researchFiles.path, file_path)
            )
          );

        return JSON.stringify({
          success: true,
          path: file_path,
          occurrences,
          message: `Replaced ${occurrences} occurrence(s) in ${file_path}`,
        });
      } catch (error) {
        return JSON.stringify({
          error: error instanceof Error ? error.message : "Failed to edit file",
        });
      }
    },
  });
}

/**
 * Create all filesystem tools for a research session
 */
export function createFilesystemTools(researchId: string): DynamicStructuredTool[] {
  return [
    createLsTool(researchId),
    createReadFileTool(researchId),
    createWriteFileTool(researchId),
    createEditFileTool(researchId),
  ];
}
