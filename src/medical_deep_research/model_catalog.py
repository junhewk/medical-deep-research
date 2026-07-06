from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.request import Request, urlopen

from .provider_config import DEEPSEEK_DEFAULT_MODEL


MODELS_DEV_URL = "https://models.dev/api.json"
MODEL_CATALOG_TTL_SECONDS = 60 * 60 * 12

BUILTIN_PROVIDER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "claude-sonnet-4-6": "Claude Sonnet 4.6",
        "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    },
    "openai": {
        "gpt-4.1-mini": "GPT-4.1 Mini",
        "gpt-5-mini": "GPT-5 Mini",
        "gpt-5": "GPT-5",
        "gpt-5.2": "GPT-5.2",
    },
    "codex": {
        "gpt-5.4-mini": "GPT-5.4 Mini Codex",
        "gpt-5.4": "GPT-5.4 Codex",
        "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
    },
    "deepseek": {
        "deepseek-v4-pro": "DeepSeek V4 Pro",
        "deepseek-v4-flash": "DeepSeek V4 Flash",
    },
    "google": {
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
        "gemini-3-flash-preview": "Gemini 3.0 Flash Preview",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
    },
    "local": {
        "qwen3.5-27b": "Qwen 3.5 27B",
        "qwen2.5:14b": "Qwen 2.5 14B",
        "llama3.1:8b": "Llama 3.1 8B",
        "mistral-small": "Mistral Small",
    },
}

DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-5-mini",
    "codex": "gpt-5.4-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "deepseek": DEEPSEEK_DEFAULT_MODEL,
    "google": "gemini-2.5-flash",
    "local": "qwen3.5-27b",
}

_LIVE_CACHE: tuple[float, dict[str, dict[str, str]]] | None = None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _display_name(model_id: str, payload: dict[str, Any] | None = None) -> str:
    if payload:
        for key in ("name", "display_name", "displayName", "label"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return model_id


def _extract_models(provider: str, data: dict[str, Any]) -> dict[str, str]:
    provider_payload = data.get(provider)
    if not isinstance(provider_payload, dict):
        return {}
    models_payload = provider_payload.get("models") or provider_payload.get("model")
    if isinstance(models_payload, dict):
        return {
            str(model_id): _display_name(
                str(model_id), item if isinstance(item, dict) else None
            )
            for model_id, item in models_payload.items()
        }
    if isinstance(models_payload, list):
        models: dict[str, str] = {}
        for item in models_payload:
            if isinstance(item, str):
                models[item] = item
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
                if isinstance(model_id, str) and model_id.strip():
                    models[model_id] = _display_name(model_id, item)
        return models
    return {}


def _fetch_models_dev(timeout_seconds: float = 3.0) -> dict[str, dict[str, str]]:
    request = Request(
        MODELS_DEV_URL,
        headers={"User-Agent": "MedicalDeepResearch/2.9.9"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public catalog URL.
        raw = response.read(2_000_000)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {
        provider: _extract_models(provider, payload)
        for provider in ("openai", "anthropic", "google", "deepseek")
    }


def _live_provider_models() -> dict[str, dict[str, str]]:
    global _LIVE_CACHE
    now = time.monotonic()
    if _LIVE_CACHE and _LIVE_CACHE[0] > now:
        return _LIVE_CACHE[1]
    try:
        live = _fetch_models_dev()
    except Exception:
        live = {}
    _LIVE_CACHE = (now + MODEL_CATALOG_TTL_SECONDS, live)
    return live


def provider_model_options(
    provider: str, *, include_live: bool | None = None
) -> dict[str, str]:
    normalized = (provider or "").strip().lower()
    models = dict(BUILTIN_PROVIDER_MODELS.get(normalized, {}))
    should_fetch = (
        _env_flag("MDR_ENABLE_MODEL_CATALOG_FETCH")
        if include_live is None
        else include_live
    )
    if should_fetch:
        for model_id, label in _live_provider_models().get(normalized, {}).items():
            models.setdefault(model_id, label)
    return models


def default_model_for_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    return DEFAULT_MODELS.get(normalized, DEFAULT_MODELS["openai"])
