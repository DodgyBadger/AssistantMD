"""
API client for V2 validation scenarios.

Provides high-level API testing capabilities backed by a FastAPI TestClient
supplied by the system controller so scenarios exercise the same app instance
that the validation runtime bootstraps.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient

from core.logger import UnifiedLogger

from validation.core.models import APIResponse, CommandResult


class APIClient:
    """Client for AssistantMD API and CLI testing."""

    def __init__(self, test_data_root: Path, client: TestClient):
        self.logger = UnifiedLogger(tag="api-client")
        self.test_data_root = Path(test_data_root)
        self.test_data_root.mkdir(parents=True, exist_ok=True)
        self._client = client

        # Track interactions for artifact logging
        self.api_calls: list[Dict[str, Any]] = []
        self.cli_commands: list[Dict[str, Any]] = []

        # Ensure API sees test vaults by default
        os.environ.setdefault("VAULTS_ROOT_PATH", str(self.test_data_root))

    # === PUBLIC API ===

    def call_api(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> APIResponse:
        """Call AssistantMD API endpoint through FastAPI TestClient."""
        method = method.upper()
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "endpoint": endpoint,
            "data": data,
            "params": params,
        }

        response = None
        try:
            response = self._client.request(
                method=method,
                url=endpoint,
                json=data,
                params=params,
                headers=headers,
            )
        finally:
            # Even if request blows up we record the attempt
            self.api_calls.append(interaction)

        payload: Optional[dict] = None
        text = ""

        if response is not None:
            text = response.text
            try:
                payload = response.json()
            except ValueError:
                payload = None

            interaction["status_code"] = response.status_code
            if payload is not None:
                interaction["response"] = payload
            else:
                interaction["response_text"] = text

        return APIResponse(
            status_code=response.status_code if response else 0,
            data=payload,
            text=text,
        )

    def launcher_command(self, command: str) -> CommandResult:
        """
        Execute launcher CLI command.

        Placeholder implementation until launcher commands are wired in.
        """
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "command": command,
        }
        self.cli_commands.append(interaction)

        if "status" in command:
            return CommandResult(0, "Vaults: 1\nScheduler: Running", "")
        if "create" in command:
            return CommandResult(0, "Vault created successfully", "")
        if "--help" in command:
            return CommandResult(0, "Usage: launcher [command]", "")
        return CommandResult(1, "", "Unknown command")

    def save_interaction_log(self, log_file: Path):
        """Save all API and CLI interactions to single log file."""
        with open(log_file, "w") as handle:
            handle.write("# System Interactions Log\n\n")

            if self.api_calls:
                handle.write("## API Calls\n\n")
                for call in self.api_calls:
                    timestamp = call["timestamp"]
                    method = call["method"]
                    endpoint = call["endpoint"]
                    status = call.get("status_code", "n/a")
                    handle.write(f"**{timestamp}**: {method} {endpoint} → {status}\n")
                    if call.get("params"):
                        handle.write(f"  Params: {json.dumps(call['params'], indent=2)}\n")
                    if call.get("data"):
                        handle.write(f"  Payload: {json.dumps(call['data'], indent=2)}\n")
                    if call.get("response"):
                        handle.write(
                            f"  Response: {json.dumps(call['response'], indent=2)}\n"
                        )
                    elif call.get("response_text"):
                        handle.write(f"  Response Text: {call['response_text']}\n")
                    handle.write("\n")

            if self.cli_commands:
                handle.write("## CLI Commands\n\n")
                for cmd in self.cli_commands:
                    handle.write(f"**{cmd['timestamp']}**: {cmd['command']}\n\n")

    def shutdown(self):
        """No-op for compatibility; lifetime managed by the system controller."""
        return None
