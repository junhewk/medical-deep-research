from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import Settings


CODEX_RUNTIME_DOWNLOAD_URL = "https://github.com/junhewk/medical-deep-research/releases/latest"


def _login_timeout_seconds() -> float:
    raw = os.getenv("MDR_CODEX_LOGIN_TIMEOUT_SECONDS", "600")
    try:
        value = float(raw)
    except ValueError:
        return 600.0
    return value if value > 0 else 600.0


class CodexRuntimeStatus(BaseModel):
    available: bool
    error: str | None = None
    download_url: str | None = CODEX_RUNTIME_DOWNLOAD_URL
    codex_bin_path: str | None = None


class CodexAuthStatus(BaseModel):
    configured: bool = False
    account_email: str | None = None
    plan_type: str | None = None
    requires_openai_auth: bool | None = None
    error: str | None = None
    runtime_available: bool = True
    runtime_error: str | None = None
    runtime_download_url: str | None = CODEX_RUNTIME_DOWNLOAD_URL


def check_codex_runtime(
    import_module: Callable[[str], Any] = importlib.import_module,
) -> CodexRuntimeStatus:
    try:
        import_module("openai_codex")
    except ImportError:
        return CodexRuntimeStatus(
            available=False,
            error="Codex Python SDK is missing from this app build.",
        )

    try:
        codex_cli_bin = import_module("codex_cli_bin")
    except ImportError:
        return CodexRuntimeStatus(
            available=False,
            error="Bundled Codex runtime package is missing from this app build.",
        )

    try:
        bundled_codex_path = getattr(codex_cli_bin, "bundled_codex_path")
        codex_bin_path = Path(bundled_codex_path())
    except (AttributeError, OSError) as exc:
        return CodexRuntimeStatus(
            available=False,
            error=f"Bundled Codex runtime is invalid: {exc}",
        )

    try:
        is_file = codex_bin_path.is_file()
    except OSError as exc:
        return CodexRuntimeStatus(
            available=False,
            error=f"Bundled Codex runtime cannot be inspected: {exc}",
        )
    if not is_file:
        return CodexRuntimeStatus(
            available=False,
            error=f"Bundled Codex executable was not found at {codex_bin_path}.",
        )

    return CodexRuntimeStatus(
        available=True,
        codex_bin_path=str(codex_bin_path),
    )


def _status_runtime_fields(runtime_status: CodexRuntimeStatus) -> dict[str, Any]:
    return {
        "runtime_available": runtime_status.available,
        "runtime_error": runtime_status.error,
        "runtime_download_url": runtime_status.download_url,
    }


def _runtime_unavailable_error(runtime_status: CodexRuntimeStatus) -> RuntimeError:
    return RuntimeError(runtime_status.error or "Bundled Codex runtime is unavailable.")


def _ensure_codex_runtime_available() -> CodexRuntimeStatus:
    runtime_status = check_codex_runtime()
    if not runtime_status.available:
        raise _runtime_unavailable_error(runtime_status)
    return runtime_status


def _codex_sdk() -> tuple[type[Any], type[Any]]:
    try:
        from openai_codex import AsyncCodex, CodexConfig
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("Install the `codex` extra to enable ChatGPT OAuth auth.") from exc
    return AsyncCodex, CodexConfig


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


class CodexAuthManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def runtime_status(self) -> CodexRuntimeStatus:
        return check_codex_runtime()

    @property
    def codex_home_path(self) -> Path:
        return self._settings.codex_home_path.expanduser().resolve()

    @property
    def auth_json_path(self) -> Path:
        return self.codex_home_path / "auth.json"

    def cache_present(self) -> bool:
        try:
            return self.auth_json_path.is_file() and self.auth_json_path.stat().st_size > 0
        except OSError:
            return False

    def _config(self) -> Any:
        AsyncCodex, CodexConfig = _codex_sdk()
        del AsyncCodex
        self.codex_home_path.mkdir(parents=True, exist_ok=True)
        return CodexConfig(
            env={"CODEX_HOME": str(self.codex_home_path)},
            config_overrides=('cli_auth_credentials_store="file"',),
            client_name="medical_deep_research",
            client_title="Medical Deep Research",
        )

    async def status(self, *, refresh: bool = False) -> CodexAuthStatus:
        runtime_status = check_codex_runtime()
        if self.cache_present() and not refresh:
            return CodexAuthStatus(
                configured=True,
                error=runtime_status.error if not runtime_status.available else None,
                **_status_runtime_fields(runtime_status),
            )

        if not runtime_status.available:
            return CodexAuthStatus(
                configured=self.cache_present(),
                error=runtime_status.error,
                **_status_runtime_fields(runtime_status),
            )

        try:
            AsyncCodex, _CodexConfig = _codex_sdk()
        except RuntimeError as exc:
            return CodexAuthStatus(
                configured=self.cache_present(),
                error=str(exc),
                **_status_runtime_fields(runtime_status),
            )

        try:
            async with AsyncCodex(config=self._config()) as codex:
                response = await codex.account(refresh_token=refresh)
        except Exception as exc:  # pragma: no cover - SDK/runtime boundary
            return CodexAuthStatus(
                configured=self.cache_present(),
                error=f"{type(exc).__name__}: {exc}",
                **_status_runtime_fields(runtime_status),
            )

        account = getattr(response, "account", None)
        account_root = getattr(account, "root", None)
        return CodexAuthStatus(
            configured=account_root is not None or self.cache_present(),
            account_email=getattr(account_root, "email", None),
            plan_type=_enum_value(getattr(account_root, "plan_type", None)),
            requires_openai_auth=getattr(response, "requires_openai_auth", None),
            **_status_runtime_fields(runtime_status),
        )

    async def login_browser(self, open_url: Callable[[str], None] | None = None) -> CodexAuthStatus:
        _ensure_codex_runtime_available()
        AsyncCodex, _CodexConfig = _codex_sdk()
        async with AsyncCodex(config=self._config()) as codex:
            login = await codex.login_chatgpt()
            if open_url is not None:
                open_url(login.auth_url)
            try:
                await asyncio.wait_for(login.wait(), timeout=_login_timeout_seconds())
            except asyncio.TimeoutError:
                await login.cancel()
                raise
        return await self.status(refresh=True)

    async def login_device_code(
        self,
        on_code: Callable[[str, str], None] | None = None,
    ) -> CodexAuthStatus:
        _ensure_codex_runtime_available()
        AsyncCodex, _CodexConfig = _codex_sdk()
        async with AsyncCodex(config=self._config()) as codex:
            login = await codex.login_chatgpt_device_code()
            if on_code is not None:
                on_code(login.verification_url, login.user_code)
            try:
                await asyncio.wait_for(login.wait(), timeout=_login_timeout_seconds())
            except asyncio.TimeoutError:
                await login.cancel()
                raise
        return await self.status(refresh=True)

    async def logout(self) -> CodexAuthStatus:
        _ensure_codex_runtime_available()
        AsyncCodex, _CodexConfig = _codex_sdk()
        async with AsyncCodex(config=self._config()) as codex:
            await codex.logout()
        return await self.status(refresh=False)
