import { ChatOpenAI } from "@langchain/openai";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatGoogleGenerativeAI } from "@langchain/google-genai";

/**
 * Shared LLM Factory
 *
 * Consolidates LLM creation logic used across multiple tools:
 * - query-context-analyzer
 * - population-validator
 * - claim-verifier
 */

export type LLMProvider = "openai" | "anthropic" | "google";
export type SupportedLLM = ChatOpenAI | ChatAnthropic | ChatGoogleGenerativeAI;

/**
 * Default fast models for each provider
 * These are cost-effective models suitable for tool operations
 */
export const DEFAULT_FAST_MODELS: Record<LLMProvider, string> = {
  anthropic: "claude-3-5-haiku-20241022",
  google: "gemini-1.5-flash",
  openai: "gpt-4o-mini",
};

/**
 * Create an LLM instance for the specified provider
 *
 * @param provider - LLM provider (openai, anthropic, google)
 * @param apiKey - API key for the provider
 * @param model - Optional model name (defaults to fast model for provider)
 * @param temperature - Temperature setting (defaults to 0.1 for deterministic output)
 */
export function createLLM(
  provider: LLMProvider,
  apiKey: string,
  model?: string,
  temperature: number = 0.1
): SupportedLLM {
  const defaultModel = DEFAULT_FAST_MODELS[provider];

  if (provider === "anthropic") {
    return new ChatAnthropic({
      modelName: model || defaultModel,
      anthropicApiKey: apiKey,
      temperature,
    });
  }

  if (provider === "google") {
    return new ChatGoogleGenerativeAI({
      model: model || defaultModel,
      apiKey,
      temperature,
    });
  }

  // Default to OpenAI
  return new ChatOpenAI({
    modelName: model || defaultModel,
    openAIApiKey: apiKey,
    temperature,
  });
}

/**
 * Create an LLM with temperature 0 for verification tasks
 * (claim verification, population validation)
 */
export function createVerifierLLM(
  provider: LLMProvider,
  apiKey: string,
  model?: string
): SupportedLLM {
  return createLLM(provider, apiKey, model, 0);
}
