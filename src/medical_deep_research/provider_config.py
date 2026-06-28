from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
LOCAL_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"


MODEL_ALIASES_BY_PROVIDER: dict[str, dict[str, str]] = {
    "anthropic": {
        "Claude Sonnet 4.6": "claude-sonnet-4-6",
        "Claude Haiku 4.5": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "GPT-4.1 Mini": "gpt-4.1-mini",
        "GPT-5 Mini": "gpt-5-mini",
        "GPT-5": "gpt-5",
        "GPT-5.2": "gpt-5.2",
    },
    "codex": {
        "GPT-5.4 Codex": "gpt-5.4",
        "GPT-5.4 Mini Codex": "gpt-5.4-mini",
        "GPT-5.3 Codex Spark": "gpt-5.3-codex-spark",
    },
    "deepseek": {
        "DeepSeek V4 Pro": "deepseek-v4-pro",
        "DeepSeek V4 Flash": "deepseek-v4-flash",
    },
    "google": {
        "Gemini 2.5 Flash": "gemini-2.5-flash",
        "Gemini 2.5 Pro": "gemini-2.5-pro",
        "Gemini 3.0 Flash Preview": "gemini-3-flash-preview",
        "Gemini 3.1 Pro Preview": "gemini-3.1-pro-preview",
    },
    "local": {
        "Qwen 3.5 27B": "qwen3.5-27b",
        "Qwen 2.5 14B": "qwen2.5:14b",
        "Llama 3.1 8B": "llama3.1:8b",
        "Mistral Small": "mistral-small",
    },
}


def normalize_model_id(provider: str, model: str | None) -> str:
    value = (model or "").strip()
    if not value:
        return DEEPSEEK_DEFAULT_MODEL if provider == "deepseek" else ""

    aliases = MODEL_ALIASES_BY_PROVIDER.get(provider, {})
    if value in aliases:
        return aliases[value]

    folded = value.casefold()
    for label, model_id in aliases.items():
        if label.casefold() == folded:
            return model_id
    return value


def normalize_local_base_url(base_url: str | None) -> str:
    value = (base_url or LOCAL_DEFAULT_BASE_URL).strip().rstrip("/")
    if not value:
        return LOCAL_DEFAULT_BASE_URL

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    path = parsed.path.rstrip("/")
    if path == "/v1" or path.endswith("/v1"):
        return urlunsplit(parsed._replace(path=path))
    if path in {"", "/", "/api"} or path.endswith("/api"):
        base_path = path[:-4] if path.endswith("/api") else path
        return urlunsplit(parsed._replace(path=(base_path.rstrip("/") + "/v1")))
    return value


def local_base_url(api_keys: dict[str, str]) -> str:
    return normalize_local_base_url(
        api_keys.get("local_base_url")
        or os.getenv("MDR_LOCAL_BASE_URL")
        or api_keys.get("ollama_base_url")
        or os.getenv("MDR_OLLAMA_BASE_URL")
        or LOCAL_DEFAULT_BASE_URL
    )


def deepseek_api_key(api_keys: dict[str, str]) -> str:
    return (api_keys.get("deepseek") or os.getenv("DEEPSEEK_API_KEY") or "").strip()


def deepseek_reasoning_effort() -> str:
    raw = (os.getenv("MDR_DEEPSEEK_REASONING_EFFORT") or "high").strip().lower()
    if raw == "xhigh":
        return "max"
    if raw in {"low", "medium"}:
        return "high"
    return raw if raw in {"high", "max"} else "high"


def deepseek_thinking_body() -> dict[str, dict[str, str]]:
    raw = (os.getenv("MDR_DEEPSEEK_THINKING") or "disabled").strip().lower()
    mode = raw if raw in {"enabled", "disabled"} else "disabled"
    return {"thinking": {"type": mode}}
