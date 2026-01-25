"""
Piston code execution tool implementation.

Provides multi-language code execution via the public Piston API (or a
user-provided endpoint). Defaults to the public instance so new users can run
code without setup.
"""

import os
from typing import Any, Dict, List, Optional

import httpx
from pydantic_ai.tools import Tool

from core.logger import UnifiedLogger
from core.settings.secrets_store import get_secret_value
from core.settings.store import get_general_settings
from .base import BaseTool

logger = UnifiedLogger(tag="piston-code-exec")


DEFAULT_BASE_URL = "https://emkc.org/api/v2/piston"

# Light heuristic for file naming so runtimes get a sensible extension.
FILE_NAME_BY_LANGUAGE = {
    "python": "main.py",
    "javascript": "main.js",
    "typescript": "main.ts",
    "bash": "main.sh",
    "sh": "main.sh",
    "go": "main.go",
    "rust": "main.rs",
    "java": "Main.java",
    "c": "main.c",
    "c++": "main.cpp",
    "cpp": "main.cpp",
    "c#": "Main.cs",
}


class PistonClient:
    """Small HTTP client wrapper around the Piston API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._runtime_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _load_runtimes(self, client: httpx.AsyncClient) -> None:
        """Fetch available runtimes once and cache by language/alias."""
        if self._runtime_cache:
            return

        response = await client.get(
            f"{self.base_url}/runtimes", headers=self._headers(), timeout=15.0
        )
        response.raise_for_status()
        runtimes = response.json()

        for runtime in runtimes:
            language = runtime.get("language", "").lower()
            aliases = runtime.get("aliases", []) or []
            for key in [language, *aliases]:
                self._runtime_cache.setdefault(key, []).append(runtime)

    @staticmethod
    def _split_language_version(language: str) -> tuple[str, Optional[str]]:
        """Support language@version override."""
        if "@" in language:
            lang, version = language.split("@", 1)
            return lang.strip().lower(), version.strip()
        return language.strip().lower(), None

    async def _resolve_runtime(
        self, language: str, client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        """Pick a runtime that matches the requested language/version."""
        await self._load_runtimes(client)
        lang_name, version = self._split_language_version(language)
        matches = self._runtime_cache.get(lang_name, [])
        if not matches:
            raise ValueError(
                f"Piston runtime not found for language '{language}'. "
                "Check available runtimes via /runtimes or choose a supported alias."
            )

        if version:
            for runtime in matches:
                if runtime.get("version") == version:
                    return runtime
            raise ValueError(
                f"Piston runtime not found for language '{lang_name}' "
                f"with version '{version}'."
            )

        return matches[0]

    async def execute_code(
        self, code: str, language: str = "python", stdin: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute code via Piston and return the raw response JSON."""
        async with httpx.AsyncClient() as client:
            runtime = await self._resolve_runtime(language, client)
            file_name = FILE_NAME_BY_LANGUAGE.get(
                runtime.get("language", "").lower(), "main.txt"
            )

            payload: Dict[str, Any] = {
                "language": runtime["language"],
                "version": runtime["version"],
                "files": [{"name": file_name, "content": code}],
            }

            if stdin:
                payload["stdin"] = stdin

            response = await client.post(
                f"{self.base_url}/execute",
                headers=self._headers(),
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()


class CodeExecutionPiston(BaseTool):
    """Code execution tool using Piston API."""

    @classmethod
    def get_tool(cls, vault_path: str = None):
        """Get the Pydantic AI tool for Piston code execution."""
        settings_entry = get_general_settings().get("piston_base_url")
        configured_base = getattr(settings_entry, "value", None) if settings_entry else None
        base_url = configured_base or os.getenv("PISTON_BASE_URL", DEFAULT_BASE_URL)
        api_key = get_secret_value("PISTON_API_KEY")
        client = PistonClient(base_url=base_url, api_key=api_key)

        async def execute_code(
            code: str, language: str = "python", stdin: Optional[str] = None
        ) -> str:
            """Execute code with the Piston multi-language sandbox.

            Args:
                code: Code to run.
                language: Language name (supports aliases). Use language@version to
                    pin a specific runtime (e.g., python@3.10.0).
                stdin: Optional stdin content to pass to the program.
            """
            try:
                logger.set_sinks(["validation"]).info(
                    "tool_invoked",
                    data={"tool": "code_execution"},
                )
                result = await client.execute_code(code, language=language, stdin=stdin)
            except httpx.HTTPError as exc:
                logger.error("Piston HTTP error", metadata={"error": str(exc)})
                return f"Piston API error: {exc}"
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Piston execution failed", metadata={"error": str(exc)})
                return f"Piston execution error: {exc}"

            response_parts: List[str] = []

            compile_info = result.get("compile") or {}
            run_info = result.get("run") or {}

            if compile_info.get("stdout"):
                response_parts.append(f"Compile output:\n{compile_info['stdout']}")
            if compile_info.get("stderr"):
                response_parts.append(f"Compile errors:\n{compile_info['stderr']}")

            stdout = run_info.get("stdout") or ""
            stderr = run_info.get("stderr") or ""
            exit_code = run_info.get("code")
            signal = run_info.get("signal")

            if stdout:
                response_parts.append(f"Output:\n{stdout}")
            if stderr:
                response_parts.append(f"Errors:\n{stderr}")
            if signal:
                response_parts.append(f"Signal: {signal}")
            if exit_code not in (None, 0):
                response_parts.append(f"Exit code: {exit_code}")

            if response_parts:
                return "Code execution completed:\n\n" + "\n\n".join(response_parts)
            return "Code executed successfully (no output)"

        return Tool(execute_code, name="execute_code")

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for Piston code execution."""
        return (
            "Code execution using the Piston API (public endpoint by default, "
            "set PISTON_BASE_URL for self-hosted). Supports many languages; "
            "pass language or language@version (e.g., python@3.10.0). "
            "Optional stdin is supported."
        )
