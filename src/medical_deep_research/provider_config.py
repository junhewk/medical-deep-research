from __future__ import annotations

import os


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"


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
    raw = (os.getenv("MDR_DEEPSEEK_THINKING") or "enabled").strip().lower()
    mode = raw if raw in {"enabled", "disabled"} else "enabled"
    return {"thinking": {"type": mode}}
