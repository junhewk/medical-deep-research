import fs from "fs/promises";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "..", "data", "research");

export interface StateExportData {
  phase?: string;
  progress?: number;
  planningSteps?: Array<{ id: string; name: string; status: string }>;
  searchResults?: unknown[];
  synthesizedContent?: string;
}

export async function ensureResearchDir(researchId: string): Promise<string> {
  const researchDir = path.join(DATA_DIR, researchId);

  try {
    await fs.mkdir(researchDir, { recursive: true });
  } catch {
    // Directory may already exist
  }

  return researchDir;
}

export async function exportStateToMarkdown(
  researchId: string,
  phase: string,
  state: Partial<StateExportData>
): Promise<string> {
  const researchDir = await ensureResearchDir(researchId);
  const stateFilePath = path.join(researchDir, "state.md");

  const timestamp = new Date().toISOString();

  let content = `# Research State: ${researchId}

**Last Updated:** ${timestamp}
**Phase:** ${phase}
**Progress:** ${state.progress || 0}%

---

## Planning Steps

`;

  if (state.planningSteps && state.planningSteps.length > 0) {
    for (const step of state.planningSteps) {
      const icon = step.status === "completed" ? "[x]" : step.status === "in_progress" ? "[-]" : "[ ]";
      content += `- ${icon} ${step.name}\n`;
    }
  } else {
    content += "No planning steps recorded.\n";
  }

  content += `
---

## Search Results Summary

`;

  if (state.searchResults && state.searchResults.length > 0) {
    content += `Found ${state.searchResults.length} results.\n\n`;
    // Add first few results as examples
    const preview = state.searchResults.slice(0, 5);
    for (const result of preview) {
      if (typeof result === "object" && result !== null) {
        const r = result as Record<string, unknown>;
        content += `- ${r.title || "Untitled"}\n`;
        if (r.pmid) content += `  - PMID: ${r.pmid}\n`;
        if (r.evidenceLevel) content += `  - Evidence: ${r.evidenceLevel}\n`;
      }
    }
    if (state.searchResults.length > 5) {
      content += `\n... and ${state.searchResults.length - 5} more results.\n`;
    }
  } else {
    content += "No search results yet.\n";
  }

  content += `
---

## Synthesized Content

`;

  if (state.synthesizedContent) {
    content += state.synthesizedContent;
  } else {
    content += "Report synthesis pending.\n";
  }

  await fs.writeFile(stateFilePath, content, "utf-8");

  return stateFilePath;
}

export async function exportFinalReport(
  researchId: string,
  reportContent: string,
  title: string
): Promise<string> {
  const researchDir = await ensureResearchDir(researchId);
  const reportFilePath = path.join(researchDir, "report.md");

  const timestamp = new Date().toISOString();

  const content = `# ${title}

**Generated:** ${timestamp}
**Research ID:** ${researchId}

---

${reportContent}
`;

  await fs.writeFile(reportFilePath, content, "utf-8");

  return reportFilePath;
}

export async function readResearchState(researchId: string): Promise<string | null> {
  const stateFilePath = path.join(DATA_DIR, researchId, "state.md");

  try {
    return await fs.readFile(stateFilePath, "utf-8");
  } catch {
    return null;
  }
}

export async function readFinalReport(researchId: string): Promise<string | null> {
  const reportFilePath = path.join(DATA_DIR, researchId, "report.md");

  try {
    return await fs.readFile(reportFilePath, "utf-8");
  } catch {
    return null;
  }
}

export async function listResearchFiles(researchId: string): Promise<string[]> {
  const researchDir = path.join(DATA_DIR, researchId);

  try {
    return await fs.readdir(researchDir);
  } catch {
    return [];
  }
}
