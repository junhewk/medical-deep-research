import { tool } from "@langchain/core/tools";
import { z } from "zod";
import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";

const TRANSLATION_PROMPT = `You are a medical research translator specializing in accurate, professional translation.
Translate the research report to Korean (한국어).

## CRITICAL: Preserve in English
The following MUST remain in English without translation:
- Medical acronyms: PICO, PCC, MeSH, PMID, DOI, LVEF, HR, CI, RCT, OR, RR, NNT, NNH, eGFR, HbA1c, BMI
- Evidence levels: Level I, Level II, Level III, Level IV, Level V
- Author names (e.g., "Smith AB, Jones CD")
- Journal names (e.g., "New England Journal of Medicine", "JAMA", "Lancet")
- Database names: PubMed, Scopus, Cochrane, MEDLINE
- Statistical values and confidence intervals (e.g., "HR 0.87, 95% CI 0.73-1.04")
- P-values (e.g., "p < 0.001")
- Citation numbers: [1], [2], [3], etc.
- DOI and PMID identifiers (e.g., "doi:10.1000/example", "PMID: 12345678")
- Study names/acronyms (e.g., "EMPEROR-Preserved trial", "DAPA-HF")
- Drug/compound names when commonly used in English form

## Translate to Korean
- Section headers:
  - "Summary" or "Executive Summary" → "요약"
  - "Background" → "배경"
  - "Methods" → "방법"
  - "Results" → "결과"
  - "Discussion" → "고찰"
  - "Conclusion" or "Conclusions" → "결론"
  - "References" → "참고문헌"
  - "Key Findings" → "주요 발견"
  - "Clinical Implications" → "임상적 시사점"
  - "Limitations" → "제한점"
- All descriptive and analytical text
- Clinical interpretations and explanations
- Transition phrases and connectors

## Formatting Rules
- Maintain all markdown formatting exactly (headers, lists, bold, italics)
- Keep the same paragraph structure
- Preserve all line breaks and spacing
- Keep reference formatting intact in the References section

## Translation Style
- Use formal academic Korean (학술적 문체)
- Use appropriate medical terminology in Korean where standard terms exist
- Maintain scientific precision and objectivity
- Keep sentences clear and concise`;

function createLLM(
  provider: "openai" | "anthropic" | "google",
  model: string,
  apiKey: string
) {
  if (provider === "anthropic") {
    return new ChatAnthropic({
      modelName: model,
      anthropicApiKey: apiKey,
      temperature: 0.2, // Lower temperature for translation accuracy
    });
  }
  if (provider === "google") {
    return new ChatGoogleGenerativeAI({
      model: model,
      apiKey: apiKey,
      temperature: 0.2,
    });
  }
  return new ChatOpenAI({
    modelName: model,
    openAIApiKey: apiKey,
    temperature: 0.2,
  });
}

export const reportTranslatorTool = tool(
  async ({
    content,
    apiKey,
    llmProvider,
    model,
  }: {
    content: string;
    apiKey: string;
    llmProvider: "openai" | "anthropic" | "google";
    model: string;
  }): Promise<string> => {
    if (!content || content.trim().length === 0) {
      return content;
    }

    const llm = createLLM(llmProvider, model, apiKey);

    const response = await llm.invoke([
      { role: "system", content: TRANSLATION_PROMPT },
      { role: "user", content: `Translate the following research report to Korean:\n\n${content}` },
    ]);

    const translatedContent = typeof response.content === "string"
      ? response.content
      : Array.isArray(response.content)
        ? response.content.map(c => typeof c === "string" ? c : "text" in c ? c.text : "").join("")
        : "";

    return translatedContent;
  },
  {
    name: "report_translator",
    description: "Translates a completed research report to Korean while preserving medical terminology, citations, and formatting in English",
    schema: z.object({
      content: z.string().describe("The complete research report content to translate"),
      apiKey: z.string().describe("API key for the LLM provider"),
      llmProvider: z.enum(["openai", "anthropic", "google"]).describe("LLM provider to use for translation"),
      model: z.string().describe("Model ID to use for translation"),
    }),
  }
);

/**
 * Direct function for calling translation without going through tool interface
 * Used by the translation node in the agent workflow
 */
export async function translateReport(
  content: string,
  apiKey: string,
  llmProvider: "openai" | "anthropic" | "google",
  model: string
): Promise<string> {
  return reportTranslatorTool.invoke({
    content,
    apiKey,
    llmProvider,
    model,
  });
}
