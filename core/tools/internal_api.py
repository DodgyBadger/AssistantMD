"""Read-only tool for allowlisted internal API metadata endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pydantic_ai.tools import Tool

from core.constants import INTERNAL_API_ALLOWED_ENDPOINTS, INTERNAL_API_MAX_RESPONSE_CHARS

from .base import BaseTool


class InternalApi(BaseTool):
    """Read-only access to a small allowlist of internal metadata endpoints."""

    allow_routing = False
    _MAX_RESPONSE_CHARS = INTERNAL_API_MAX_RESPONSE_CHARS
    _ALLOWED_ENDPOINTS = INTERNAL_API_ALLOWED_ENDPOINTS

    @classmethod
    def get_tool(cls, vault_path: str | None = None):
        """Get the read-only internal API tool."""

        async def internal_api(
            *,
            endpoint: str,
            vault_name: str = "",
            workflow_name: str = "",
        ) -> str:
            """Fetch structured metadata from a read-only allowlisted internal API endpoint.

            :param endpoint: One of: metadata, context_templates
            :param vault_name: Optional vault name, used for context_templates
            :param workflow_name: Reserved for future allowlisted endpoints that support workflow-name filtering
            """
            endpoint_key = (endpoint or "").strip().lower()
            if endpoint_key not in cls._ALLOWED_ENDPOINTS:
                allowed = ", ".join(sorted(cls._ALLOWED_ENDPOINTS))
                raise ValueError(f"Unsupported endpoint '{endpoint}'. Allowed endpoints: {allowed}")

            path = cls._ALLOWED_ENDPOINTS[endpoint_key]
            params: dict[str, str] = {}
            if endpoint_key == "context_templates":
                inferred_vault_name = cls._infer_vault_name(vault_path)
                effective_vault_name = (vault_name or inferred_vault_name or "").strip()
                if not effective_vault_name:
                    raise ValueError(
                        "vault_name is required for endpoint='context_templates' when vault context is unavailable"
                    )
                params["vault_name"] = effective_vault_name

            from main import app

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://internal-api") as client:
                response = await client.get(path, params=params)
            if response.status_code >= 400:
                raise ValueError(
                    f"Internal API request failed for {path}: HTTP {response.status_code} {response.text}"
                )
            payload = json.dumps(response.json(), indent=2, sort_keys=True)
            if len(payload) > cls._MAX_RESPONSE_CHARS:
                raise ValueError(
                    f"Internal API response for {endpoint_key} exceeded {cls._MAX_RESPONSE_CHARS} characters. "
                    "Use narrower filters."
                )
            return payload

        return Tool(
            internal_api,
            name="internal_api",
            description="Fetch structured metadata from a small allowlist of internal read-only API endpoints.",
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Get usage instructions for read-only internal API access."""
        return """
Fetch structured metadata from a small allowlist of internal read-only API endpoints.

This tool is not part of the normal default tool surface.

Important notes:
- read-only allowlisted endpoints only
- do not use for arbitrary URLs or mutation operations
"""

    @staticmethod
    def _infer_vault_name(vault_path: str | None) -> str | None:
        if not vault_path:
            return None
        return Path(vault_path).name or None
