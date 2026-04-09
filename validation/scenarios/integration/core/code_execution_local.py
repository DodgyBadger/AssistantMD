"""
Integration scenario for the chat-facing code_execution_local tool.

Validates deterministic cache-scoped execution through the real /api/chat/execute
path using a patched TestModel argument generator.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class CodeExecutionLocalScenario(BaseScenario):
    """Validate code_execution_local cache read/write scope enforcement."""

    async def test_scenario(self):
        vault = self.create_vault("CodeExecutionLocalVault")

        await self.start_system()

        import core.llm.chat_executor as chat_executor
        from core.context.store import get_cache_artifact, upsert_cache_artifact
        from core.runtime.state import get_runtime_context
        from pydantic_ai.models.test import TestModel

        reference_time = datetime(2026, 4, 6, 12, 0, 0)

        upsert_cache_artifact(
            owner_id=f"{vault.name}/chat/code_execution_local_allow_read",
            session_key="code_execution_local_allow_read",
            artifact_ref="tool/demo/allowed",
            cache_mode="session",
            ttl_seconds=None,
            raw_content="ALPHA BETA GAMMA",
            metadata={"origin": "validation_fixture"},
            origin="validation_fixture",
            now=reference_time,
            week_start_day=0,
        )

        current_case = {"name": "allow_read"}

        class _DeterministicToolModel(TestModel):
            def __init__(self):
                super().__init__(call_tools=["code_execution_local"])

            def gen_tool_args(self, tool_def):
                if getattr(tool_def, "name", "") != "code_execution_local":
                    return super().gen_tool_args(tool_def)

                case_name = current_case["name"]
                if case_name == "allow_read":
                    return {
                        "code": (
                            'artifact = await retrieve(type="cache", ref="tool/demo/allowed")\n'
                            "artifact.items[0].content"
                        ),
                        "readable_cache_refs": ["tool/demo/allowed"],
                        "writable_cache_refs": [],
                    }
                if case_name == "discovery":
                    return {}
                if case_name == "deny_read":
                    return {
                        "code": (
                            'artifact = await retrieve(type="cache", ref="tool/demo/allowed")\n'
                            "artifact.items[0].content"
                        ),
                        "readable_cache_refs": ["tool/demo/other"],
                        "writable_cache_refs": [],
                    }
                if case_name == "allow_write":
                    return {
                        "code": (
                            'await output(type="cache", ref="scratch/derived", data="DERIVED_RESULT")\n'
                            '"WRITE_OK"'
                        ),
                        "readable_cache_refs": [],
                        "writable_cache_refs": ["scratch/derived"],
                    }
                raise AssertionError(f"Unexpected scenario case: {case_name}")

        def _patched_prepare_agent_config(vault_name, vault_path, tools, model):
            del vault_name, vault_path, tools, model
            from core.authoring.shared.tool_binding import resolve_tool_binding

            binding = resolve_tool_binding(
                ["code_execution_local"],
                vault_path=str(vault),
            )
            return (
                "You must call code_execution_local before responding.",
                binding.tool_instructions,
                _DeterministicToolModel(),
                binding.tool_functions,
            )

        original_prepare_agent_config = chat_executor._prepare_agent_config
        chat_executor._prepare_agent_config = _patched_prepare_agent_config
        try:
            allow_read = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Read the allowed cache artifact through code_execution_local.",
                    "session_id": "code_execution_local_allow_read",
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert allow_read.status_code == 200, "Allowed cache read should succeed"
            allow_text = allow_read.json()["response"]
            self.soft_assert(
                "ALPHA BETA GAMMA" in allow_text,
                "Allowed cache read should return the cached artifact content",
            )

            current_case["name"] = "discovery"
            discovery = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Inspect code_execution_local with no arguments first.",
                    "session_id": "code_execution_local_discovery",
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert discovery.status_code == 200, "No-arg code_execution_local discovery should succeed"
            discovery_text = discovery.json()["response"]
            self.soft_assert(
                bool(discovery_text.strip()),
                "No-arg code_execution_local should return a non-empty discovery response",
            )

            current_case["name"] = "deny_read"
            deny_read = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Attempt an ungranted cache read through code_execution_local.",
                    "session_id": "code_execution_local_deny_read",
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert deny_read.status_code == 200, "Denied cache read should still return a tool result"
            deny_text = deny_read.json()["response"]
            self.soft_assert(
                "outside the configured read scope" in deny_text,
                "Denied cache read should surface the cache read scope error",
            )

            current_case["name"] = "allow_write"
            allow_write = self.call_api(
                "/api/chat/execute",
                method="POST",
                data={
                    "vault_name": vault.name,
                    "prompt": "Write a derived cache artifact through code_execution_local.",
                    "session_id": "code_execution_local_allow_write",
                    "tools": ["code_execution_local"],
                    "model": "test",
                },
            )
            assert allow_write.status_code == 200, "Allowed cache write should succeed"
            write_text = allow_write.json()["response"]
            self.soft_assert(
                "WRITE_OK" in write_text,
                "Allowed cache write should return the snippet result",
            )

            runtime = get_runtime_context()
            derived = get_cache_artifact(
                owner_id=f"{vault.name}/chat/code_execution_local_allow_write",
                session_key="code_execution_local_allow_write",
                artifact_ref="scratch/derived",
                now=reference_time,
                week_start_day=0,
                system_root=runtime.config.system_root,
            )
            assert derived is not None, "Allowed cache write should persist the derived cache artifact"
            self.soft_assert_equal(
                derived["raw_content"],
                "DERIVED_RESULT",
                "Derived cache artifact should preserve the written content",
            )
        finally:
            chat_executor._prepare_agent_config = original_prepare_agent_config
            await self.stop_system()
            self.teardown_scenario()
