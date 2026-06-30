import unittest
from unittest.mock import patch

from medical_deep_research.provider_config import deepseek_thinking_body, normalize_local_base_url, normalize_model_id
from medical_deep_research.runtime import build_runtime


class ProviderConfigTests(unittest.TestCase):
    def test_normalize_deepseek_display_label_to_api_model_id(self) -> None:
        self.assertEqual(
            normalize_model_id("deepseek", "DeepSeek V4 Flash"),
            "deepseek-v4-flash",
        )

    def test_normalize_model_id_preserves_custom_model_id(self) -> None:
        self.assertEqual(
            normalize_model_id("local", "custom-local-model"),
            "custom-local-model",
        )

    def test_normalize_local_base_url_accepts_service_roots(self) -> None:
        self.assertEqual(
            normalize_local_base_url("http://127.0.0.1:11434"),
            "http://127.0.0.1:11434/v1",
        )
        self.assertEqual(
            normalize_local_base_url("http://127.0.0.1:11434/api"),
            "http://127.0.0.1:11434/v1",
        )
        self.assertEqual(
            normalize_local_base_url("http://127.0.0.1:1234/v1"),
            "http://127.0.0.1:1234/v1",
        )

    def test_deepseek_thinking_defaults_to_disabled_for_multi_turn_agents(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(deepseek_thinking_body(), {"thinking": {"type": "disabled"}})

    def test_deepseek_thinking_env_override_allows_enabled(self) -> None:
        with patch.dict("os.environ", {"MDR_DEEPSEEK_THINKING": "enabled"}, clear=True):
            self.assertEqual(deepseek_thinking_body(), {"thinking": {"type": "enabled"}})

    def test_deepseek_thinking_invalid_env_falls_back_to_disabled(self) -> None:
        with patch.dict("os.environ", {"MDR_DEEPSEEK_THINKING": "maybe"}, clear=True):
            self.assertEqual(deepseek_thinking_body(), {"thinking": {"type": "disabled"}})

    def test_google_runtime_uses_langchain_genai_not_adk(self) -> None:
        runtime = build_runtime("google")

        self.assertEqual(runtime.runtime_name, "Google LangChain Agent")
        self.assertEqual(runtime.runtime_engine, "langchain_google_genai")
        self.assertEqual(runtime.sdk_module, "langchain_google_genai")

    def test_codex_display_label_normalizes_to_codex_model_id(self) -> None:
        self.assertEqual(
            normalize_model_id("codex", "GPT-5.4 Mini Codex"),
            "gpt-5.4-mini",
        )

    def test_codex_runtime_is_distinct_from_openai_agents(self) -> None:
        runtime = build_runtime("codex")

        self.assertEqual(runtime.runtime_name, "OpenAI Codex SDK")
        self.assertEqual(runtime.runtime_engine, "openai_codex")
        self.assertEqual(runtime.sdk_module, "openai_codex")


if __name__ == "__main__":
    unittest.main()
