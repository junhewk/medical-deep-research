from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import Settings


def _login_timeout_seconds() -> float:
    raw = os.getenv("MDR_CODEX_LOGIN_TIMEOUT_SECONDS", "600")
    try:
        value = float(raw)
    except ValueError:
        return 600.0
    return value if value > 0 else 600.0


class CodexAuthStatus(BaseModel):
    configured: bool = False
    account_email: str | None = None
    plan_type: str | None = None
    requires_openai_auth: bool | None = None
    error: str | None = None


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
        if self.cache_present() and not refresh:
            return CodexAuthStatus(configured=True)

        try:
            AsyncCodex, _CodexConfig = _codex_sdk()
        except RuntimeError as exc:
            return CodexAuthStatus(configured=self.cache_present(), error=str(exc))

        try:
            async with AsyncCodex(config=self._config()) as codex:
                response = await codex.account(refresh_token=refresh)
        except Exception as exc:  # pragma: no cover - SDK/runtime boundary
            return CodexAuthStatus(configured=self.cache_present(), error=f"{type(exc).__name__}: {exc}")

        account = getattr(response, "account", None)
        account_root = getattr(account, "root", None)
        return CodexAuthStatus(
            configured=account_root is not None or self.cache_present(),
            account_email=getattr(account_root, "email", None),
            plan_type=_enum_value(getattr(account_root, "plan_type", None)),
            requires_openai_auth=getattr(response, "requires_openai_auth", None),
        )

    async def login_browser(self, open_url: Callable[[str], None] | None = None) -> CodexAuthStatus:
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
        AsyncCodex, _CodexConfig = _codex_sdk()
        async with AsyncCodex(config=self._config()) as codex:
            await codex.logout()
        return await self.status(refresh=False)
