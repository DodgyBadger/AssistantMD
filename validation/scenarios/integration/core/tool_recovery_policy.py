"""Validate tool-owned recovery metadata and lightweight capability summaries."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.authoring.shared.tool_binding import resolve_tool_binding
from core.chat.run_recovery import ChatRunRecoveryCoordinator
from core.tools.base import BaseTool, ToolRecoveryPolicy
from validation.core.base_scenario import BaseScenario


class ToolRecoveryPolicyScenario(BaseScenario):
    """Prove recovery policy travels with tools and unknown fails closed."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("ToolRecoveryPolicyVault")
        await self.start_system()
        try:
            binding = resolve_tool_binding(
                "file_read, file_write",
                vault_path=str(vault),
            )
            specs = {spec.name: spec for spec in binding.tool_specs}
            assert specs["file_read"].recovery_policy is ToolRecoveryPolicy.REPLAY_SAFE
            assert (
                specs["file_write"].recovery_policy
                is ToolRecoveryPolicy.VAULT_TRANSACTIONAL
            )

            coordinator = ChatRunRecoveryCoordinator.from_tools(binding.tool_functions)
            assert (
                coordinator.tool_policy("file_read") is ToolRecoveryPolicy.REPLAY_SAFE
            )
            assert (
                coordinator.tool_policy("file_write")
                is ToolRecoveryPolicy.VAULT_TRANSACTIONAL
            )
            assert coordinator.tool_policy("unregistered") is ToolRecoveryPolicy.UNKNOWN
            assert BaseTool.get_recovery_policy() is ToolRecoveryPolicy.UNKNOWN

            assert "Read, list, search, and inspect frontmatter" in (
                binding.tool_instructions
            )
            assert "Create, append, edit lines, replace text" in (
                binding.tool_instructions
            )
            assert "Full documentation" not in binding.tool_instructions
            assert "__virtual_docs__" not in binding.tool_instructions
        finally:
            await self.stop_system()
            self.teardown_scenario()
