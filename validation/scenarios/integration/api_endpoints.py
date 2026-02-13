"""
Integration scenario that exercises every documented API endpoint using the
validation harness' shared FastAPI TestClient.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from validation.core.base_scenario import BaseScenario


class ApiEndpointsScenario(BaseScenario):
    """Validate core REST endpoints end-to-end using real runtime context."""

    async def test_scenario(self):
        vault = self.create_vault("IntegrationApiVault")

        # Seed a minimal step workflow for execution and status checks
        self.create_file(
            vault,
            "AssistantMD/Workflows/status_probe.md",
            STATUS_PROBE_WORKFLOW,
        )

        # Health prior to runtime bootstrap should indicate startup state
        pre_health = self.call_api("/api/health")
        assert pre_health.status_code == 503, (
            "Health reports starting state before runtime boots"
        )

        await self.start_system()

        # Core system endpoints
        health = self.call_api("/api/health")
        assert health.status_code == 200, "Health endpoint reports healthy"

        status_response = self.call_api("/api/status")
        assert status_response.status_code == 200, "Status endpoint succeeds"
        status_payload = status_response.json()
        assert status_payload.get("total_vaults") == 1, "One vault discovered"
        assert status_payload.get("total_workflows") == 1, "Seeded workflow counted"

        activity = self.call_api("/api/system/activity-log")
        assert activity.status_code == 200, "Activity log fetch succeeds"

        settings = self.call_api("/api/system/settings")
        assert settings.status_code == 200, "Settings fetch succeeds"
        settings_payload = settings.json()
        update_settings = self.call_api(
            "/api/system/settings",
            method="PUT",
            data={"content": settings_payload["content"]},
        )
        assert update_settings.status_code == 200, "Settings update round-trips"

        general_settings = self.call_api("/api/system/settings/general")
        assert general_settings.status_code == 200, "General settings load"
        general_payload = general_settings.json()
        if general_payload:
            first_setting = general_payload[0]
            update_setting = self.call_api(
                f"/api/system/settings/general/{first_setting['key']}",
                method="PUT",
                data={"value": first_setting["value"]},
            )
            assert update_setting.status_code == 200, (
                "General setting update acknowledged"
            )

        # Model configuration lifecycle (create + delete)
        models_resp = self.call_api("/api/system/models")
        assert models_resp.status_code == 200, "Model listing succeeds"
        models_payload = models_resp.json()
        base_model = models_payload[0]
        model_alias = "validation-test-model"
        created_model = self.call_api(
            f"/api/system/models/{model_alias}",
            method="PUT",
            data={
                "provider": base_model["provider"],
                "model_string": base_model["model_string"],
                "description": "Validation alias for API coverage",
            },
        )
        assert created_model.status_code == 200, "Model alias creation works"
        removed_model = self.call_api(
            f"/api/system/models/{model_alias}", method="DELETE"
        )
        assert removed_model.status_code == 200, "Model alias deletion works"

        # Provider configuration lifecycle (create + delete)
        providers_resp = self.call_api("/api/system/providers")
        assert providers_resp.status_code == 200, "Provider listing succeeds"
        provider_alias = "validation-provider"
        created_provider = self.call_api(
            f"/api/system/providers/{provider_alias}",
            method="PUT",
            data={
                "api_key": "VALIDATION_PROVIDER_KEY",
                "base_url": "VALIDATION_PROVIDER_BASE_URL",
            },
        )
        assert created_provider.status_code == 200, (
            "Provider creation acknowledged"
        )
        removed_provider = self.call_api(
            f"/api/system/providers/{provider_alias}", method="DELETE"
        )
        assert removed_provider.status_code == 200, (
            "Provider deletion acknowledged"
        )

        # Secrets endpoint lifecycle: list, set, clear (scenario-local overlay)
        secrets_list = self.call_api("/api/system/secrets")
        assert secrets_list.status_code == 200, "Secrets listing succeeds"
        secrets_payload = secrets_list.json()
        assert isinstance(secrets_payload, list), "Secrets list is returned"

        secret_update = self.call_api(
            "/api/system/secrets",
            method="PUT",
            data={"name": "VALIDATION_TEMP_SECRET", "value": "123"},
        )
        assert secret_update.status_code == 200, "Secret update succeeds"

        updated_secrets = self.call_api("/api/system/secrets")
        assert updated_secrets.status_code == 200, "Secrets refresh succeeds"
        assert any(
            entry["name"] == "VALIDATION_TEMP_SECRET" and entry["has_value"]
            for entry in updated_secrets.json()
        ), "Updated secret reported with value"

        secret_clear = self.call_api(
            "/api/system/secrets",
            method="PUT",
            data={"name": "VALIDATION_TEMP_SECRET", "value": ""},
        )
        assert secret_clear.status_code == 200, "Secret cleared successfully"

        cleared_secrets = self.call_api("/api/system/secrets")
        assert not any(
            entry["name"] == "VALIDATION_TEMP_SECRET" and entry["has_value"]
            for entry in cleared_secrets.json()
        ), "Secret list no longer reports a stored value"

        # Vault rescan should keep workflow counts stable
        rescan_response = self.call_api("/api/vaults/rescan", method="POST")
        assert rescan_response.status_code == 200, "Vault rescan succeeds"

        # Manual workflow execution
        execute_response = self.call_api(
            "/api/workflows/execute",
            method="POST",
            data={"global_id": f"{vault.name}/status_probe"},
        )
        assert execute_response.status_code == 200, (
            "Manual workflow execution succeeds"
        )
        assert execute_response.json().get("success") is True, "Workflow reports success"

        # Chat execution, metadata, history transforms
        chat_metadata = self.call_api("/api/metadata")
        assert chat_metadata.status_code == 200, "Metadata endpoint available"
        metadata_payload = chat_metadata.json()
        assert any(
            tool.get("name") == "workflow_run"
            for tool in metadata_payload.get("tools", [])
        ), "workflow_run tool is exposed in metadata"

        chat_payload = {
            "vault_name": vault.name,
            "prompt": "Say hello from integration test.",
            "tools": [],
            "model": "gpt-mini",
        }
        chat_first = self.call_api("/api/chat/execute", method="POST", data=chat_payload)
        assert chat_first.status_code == 200, "Chat execution succeeds"
        session_id = chat_first.json()["session_id"]

        chat_second = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                **chat_payload,
                "session_id": session_id,
                "prompt": "Add another thought for history depth.",
            },
        )
        assert chat_second.status_code == 200, "Follow-up chat execution succeeds"

        # Exercise workflow-run tool through chat endpoint
        checkpoint = self.event_checkpoint()
        workflow_tool_chat = self.call_api(
            "/api/chat/execute",
            method="POST",
            data={
                "vault_name": vault.name,
                "prompt": (
                    "Use workflow_run to list workflows, then run workflow "
                    "'status_probe'. You must call the tool before responding."
                ),
                "tools": ["workflow_run"],
                "model": "gpt-mini",
            },
        )
        assert workflow_tool_chat.status_code == 200, "Chat tool invocation succeeds"
        events = self.events_since(checkpoint)
        self.assert_event_contains(
            events,
            name="tool_invoked",
            expected={"tool": "workflow_run"},
        )

        await self.stop_system()
        self.teardown_scenario()


# === WORKFLOW TEMPLATES ===

STATUS_PROBE_WORKFLOW = """---
workflow_engine: step
enabled: false
description: Validation helper workflow
---

## STEP1
@output file: logs/{today}
@model gpt-mini

Summarize the validation run context.
"""
