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
            """---
workflow_engine: step
enabled: false
description: Validation helper workflow
---

## STEP1
@output-file logs/{today}
@model gpt-5-mini

Summarize the validation run context.
""",
        )

        # Health prior to runtime bootstrap should indicate startup state
        pre_health = self.call_api("/api/health")
        self.expect_equals(
            pre_health.status_code,
            503,
            "Health reports starting state before runtime boots",
        )

        await self.start_system()

        # Core system endpoints
        health = self.call_api("/api/health")
        self.expect_equals(health.status_code, 200, "Health endpoint reports healthy")

        status_response = self.call_api("/api/status")
        self.expect_equals(status_response.status_code, 200, "Status endpoint succeeds")
        status_payload = status_response.json()
        self.expect_equals(status_payload.get("total_vaults"), 1, "One vault discovered")
        self.expect_equals(status_payload.get("total_workflows"), 1, "Seeded workflow counted")

        activity = self.call_api("/api/system/activity-log")
        self.expect_equals(activity.status_code, 200, "Activity log fetch succeeds")

        settings = self.call_api("/api/system/settings")
        self.expect_equals(settings.status_code, 200, "Settings fetch succeeds")
        settings_payload = settings.json()
        update_settings = self.call_api(
            "/api/system/settings",
            method="PUT",
            data={"content": settings_payload["content"]},
        )
        self.expect_equals(update_settings.status_code, 200, "Settings update round-trips")

        general_settings = self.call_api("/api/system/settings/general")
        self.expect_equals(general_settings.status_code, 200, "General settings load")
        general_payload = general_settings.json()
        if general_payload:
            first_setting = general_payload[0]
            update_setting = self.call_api(
                f"/api/system/settings/general/{first_setting['key']}",
                method="PUT",
                data={"value": first_setting["value"]},
            )
            self.expect_equals(
                update_setting.status_code,
                200,
                "General setting update acknowledged",
            )

        # Model configuration lifecycle (create + delete)
        models_resp = self.call_api("/api/system/models")
        self.expect_equals(models_resp.status_code, 200, "Model listing succeeds")
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
        self.expect_equals(created_model.status_code, 200, "Model alias creation works")
        removed_model = self.call_api(
            f"/api/system/models/{model_alias}", method="DELETE"
        )
        self.expect_equals(removed_model.status_code, 200, "Model alias deletion works")

        # Provider configuration lifecycle (create + delete)
        providers_resp = self.call_api("/api/system/providers")
        self.expect_equals(providers_resp.status_code, 200, "Provider listing succeeds")
        provider_alias = "validation-provider"
        created_provider = self.call_api(
            f"/api/system/providers/{provider_alias}",
            method="PUT",
            data={
                "api_key": "VALIDATION_PROVIDER_KEY",
                "api_key_value": "placeholder",
                "base_url_value": "https://example.com/api",
            },
        )
        self.expect_equals(
            created_provider.status_code, 200, "Provider creation acknowledged"
        )
        removed_provider = self.call_api(
            f"/api/system/providers/{provider_alias}", method="DELETE"
        )
        self.expect_equals(
            removed_provider.status_code, 200, "Provider deletion acknowledged"
        )

        # Secrets endpoint lifecycle: list, set, clear (scenario-local overlay)
        secrets_list = self.call_api("/api/system/secrets")
        self.expect_equals(secrets_list.status_code, 200, "Secrets listing succeeds")
        secrets_payload = secrets_list.json()
        self.expect_equals(
            isinstance(secrets_payload, list),
            True,
            "Secrets list is returned",
        )

        secret_update = self.call_api(
            "/api/system/secrets",
            method="PUT",
            data={"name": "VALIDATION_TEMP_SECRET", "value": "123"},
        )
        self.expect_equals(secret_update.status_code, 200, "Secret update succeeds")

        updated_secrets = self.call_api("/api/system/secrets")
        self.expect_equals(updated_secrets.status_code, 200, "Secrets refresh succeeds")
        self.expect_equals(
            any(
                entry["name"] == "VALIDATION_TEMP_SECRET" and entry["has_value"]
                for entry in updated_secrets.json()
            ),
            True,
            "Updated secret reported with value",
        )

        secret_clear = self.call_api(
            "/api/system/secrets",
            method="PUT",
            data={"name": "VALIDATION_TEMP_SECRET", "value": ""},
        )
        self.expect_equals(secret_clear.status_code, 200, "Secret cleared successfully")

        cleared_secrets = self.call_api("/api/system/secrets")
        self.expect_equals(
            any(
                entry["name"] == "VALIDATION_TEMP_SECRET" and entry["has_value"]
                for entry in cleared_secrets.json()
            ),
            False,
            "Secret list no longer reports a stored value",
        )

        # Vault rescan should keep workflow counts stable
        rescan_response = self.call_api("/api/vaults/rescan", method="POST")
        self.expect_equals(rescan_response.status_code, 200, "Vault rescan succeeds")

        # Manual workflow execution
        execute_response = self.call_api(
            "/api/workflows/execute",
            method="POST",
            data={"global_id": f"{vault.name}/status_probe"},
        )
        self.expect_equals(
            execute_response.status_code, 200, "Manual workflow execution succeeds"
        )
        self.expect_equals(
            execute_response.json().get("success"), True, "Workflow reports success"
        )

        # Chat execution, metadata, history transforms
        chat_metadata = self.call_api("/api/chat/metadata")
        self.expect_equals(chat_metadata.status_code, 200, "Chat metadata available")

        chat_payload = {
            "vault_name": vault.name,
            "prompt": "Say hello from integration test.",
            "tools": [],
            "model": "gpt-5-mini",
            "use_conversation_history": True,
        }
        chat_first = self.call_api("/api/chat/execute", method="POST", data=chat_payload)
        self.expect_equals(chat_first.status_code, 200, "Chat execution succeeds")
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
        self.expect_equals(
            chat_second.status_code, 200, "Follow-up chat execution succeeds"
        )

        compact_response = self.call_api(
            "/api/chat/compact",
            method="POST",
            data={
                "session_id": session_id,
                "vault_name": vault.name,
                "model": "gpt-5-mini",
                "user_instructions": "Keep it brief.",
            },
        )
        self.expect_equals(
            compact_response.status_code, 200, "Chat compact endpoint succeeds"
        )
        new_session_id = compact_response.json()["new_session_id"]

        create_workflow_response = self.call_api(
            "/api/chat/create-workflow",
            method="POST",
            data={
                "session_id": new_session_id,
                "vault_name": vault.name,
                "model": "gpt-5-mini",
                "user_instructions": "Outline a simple workflow.",
            },
        )
        self.expect_equals(
            create_workflow_response.status_code,
            200,
            "Workflow creation flow initializes",
        )

        await self.stop_system()
        self.teardown_scenario()
