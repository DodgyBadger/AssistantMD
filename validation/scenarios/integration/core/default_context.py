"""
Integration scenario for packaged default context loading behavior.

Validates that the default context template loads vault-level instructions,
workspace-local orientation files, and bounded user notes without depending on
the internal structure of those markdown files.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, UserPromptPart

from validation.core.base_scenario import BaseScenario


class DefaultContextScenario(BaseScenario):
    """Ensure default.md composes vault, workspace, and user context."""

    async def test_scenario(self):
        vault = self.create_vault("DefaultContextVault")
        self.create_file(
            vault,
            "AssistantMD/soul.md",
            """# Soul

Use the validation soul instruction.
""",
        )
        self.create_file(
            vault,
            "AssistantMD/PlayBook.md",
            """# Vault Playbook

Use the validation vault playbook.
""",
        )
        self.create_file(
            vault,
            "AssistantMD/user.md",
            """# User Notes

## User

- The user works on AssistantMD.

## Chat And Work Preferences

- Prefer concise engineering answers.

## Custom Section

- Custom context note sections are owned by the skill, not the context script.

## Large Section

"""
            + ("- Filler context note line that should eventually be truncated.\n" * 500)
            + """
""",
        )
        self.create_file(
            vault,
            "Projects/WorkspaceA/readme.md",
            """# Workspace A

This workspace is for validating workspace README loading.
""",
        )
        self.create_file(
            vault,
            "Projects/WorkspaceA/PLAYBOOK.md",
            """# Workspace Playbook

Use the workspace-specific validation playbook.
""",
        )

        await self.start_system()

        from core.authoring.context_manager import build_context_manager_history_processor

        session_id = "default_context_session"
        processor = build_context_manager_history_processor(
            session_id=session_id,
            vault_name=vault.name,
            vault_path=str(vault),
            model_alias="gpt",
            template_name="default.md",
            workspace_path="Projects/WorkspaceA",
        )

        processed = await processor(
            SimpleNamespace(prompt="What do you remember?", deps=SimpleNamespace()),
            [
                ModelRequest(
                    parts=[UserPromptPart(content="What do you remember?")],
                    run_id="run-user-notes",
                )
            ],
        )

        system_text = "\n\n".join(
            getattr(part, "content", "")
            for message in processed
            for part in getattr(message, "parts", ())
            if getattr(part, "part_kind", None) == "system-prompt"
        )

        self.soft_assert(
            "Use the validation soul instruction." in system_text,
            "Expected default context to load AssistantMD/soul.md",
        )
        self.soft_assert(
            "Use the validation vault playbook." in system_text,
            "Expected default context to load AssistantMD/playbook.md",
        )
        self.soft_assert(
            "This workspace is for validating workspace README loading." in system_text,
            "Expected default context to load workspace README.md",
        )
        self.soft_assert(
            "Use the workspace-specific validation playbook." in system_text,
            "Expected default context to load workspace playbook.md",
        )
        vault_playbook_index = system_text.find("Use the validation vault playbook.")
        workspace_playbook_index = system_text.find("Use the workspace-specific validation playbook.")
        self.soft_assert(
            0 <= vault_playbook_index < workspace_playbook_index,
            "Expected workspace playbook to appear after the vault playbook",
        )
        self.soft_assert(
            "## User Notes" in system_text,
            "Expected default context instructions to include user notes section",
        )
        self.soft_assert(
            "The user works on AssistantMD." in system_text,
            "Expected user context note to be injected",
        )
        self.soft_assert(
            "Prefer concise engineering answers." in system_text,
            "Expected preference context note to be injected",
        )
        self.soft_assert(
            "Custom context note sections are owned by the skill" in system_text,
            "Expected default context to preserve custom context note sections",
        )
        self.soft_assert(
            "[User notes truncated by default context script.]" in system_text,
            "Expected oversized user notes file to be bounded",
        )
        self.soft_assert(
            system_text.count("Filler context note line") < 500,
            "Expected default context to truncate oversized user notes content",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
