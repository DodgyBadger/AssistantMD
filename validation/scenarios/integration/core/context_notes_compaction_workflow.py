"""
Integration scenario for the packaged vault-native context notes compaction workflow.

Validates the deterministic skip path without invoking delegate model curation.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from validation.core.base_scenario import BaseScenario


class ContextNotesCompactionWorkflowScenario(BaseScenario):
    """Ensure context notes compaction reads skill settings and skips small files."""

    async def test_scenario(self):
        vault = self.create_vault("ContextNotesCompactionWorkflowVault")
        self.create_file(
            vault,
            "AssistantMD/context_notes.md",
            "# Context Notes\n\n## User\n\n- The user works on AssistantMD.\n",
        )

        await self.start_system()

        from core.authoring.runtime import WorkflowAuthoringHost, run_authoring_monty
        from core.authoring.template_loader import load_authoring_template_file

        source = load_authoring_template_file(
            "core/authoring/seed_templates/workflows/nightly-context-notes-compaction.md"
        )
        workflow_id = f"{vault.name}/system/nightly-context-notes-compaction"

        result = await run_authoring_monty(
            workflow_id=workflow_id,
            code=source.code,
            host=WorkflowAuthoringHost(
                workflow_id=workflow_id,
                vault_path=str(vault),
                reference_date=datetime(2026, 5, 23, 2, 30, 0),
            ),
            script_name="nightly-context-notes-compaction.md",
        )

        self.soft_assert_equal(
            result.status,
            "skipped",
            "Expected workflow to skip context notes files below the compaction trigger",
        )
        self.soft_assert(
            "trigger is" in result.reason,
            "Expected skip reason to include computed trigger threshold",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
