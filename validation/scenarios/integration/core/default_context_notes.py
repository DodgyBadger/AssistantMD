"""
Integration scenario for default context loading of vault-native context notes.

Validates that the packaged default context template reads AssistantMD/context_notes.md
as bounded context without depending on the file's internal structure.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pydantic_ai.messages import ModelRequest, UserPromptPart

from validation.core.base_scenario import BaseScenario


class DefaultContextNotesScenario(BaseScenario):
    """Ensure default.md loads context_notes.md and bounds oversized content."""

    async def test_scenario(self):
        vault = self.create_vault("DefaultContextNotesVault")
        self.create_file(
            vault,
            "AssistantMD/context_notes.md",
            """# Context Notes

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

        await self.start_system()

        from core.authoring.context_manager import build_context_manager_history_processor

        session_id = "default_context_notes_session"
        processor = build_context_manager_history_processor(
            session_id=session_id,
            vault_name=vault.name,
            vault_path=str(vault),
            model_alias="gpt",
            template_name="default.md",
        )

        processed = await processor(
            SimpleNamespace(prompt="What do you remember?", deps=SimpleNamespace()),
            [
                ModelRequest(
                    parts=[UserPromptPart(content="What do you remember?")],
                    run_id="run-context-notes",
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
            "## Context Notes" in system_text,
            "Expected default context instructions to include context notes section",
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
            "[Context notes truncated by default context script.]" in system_text,
            "Expected oversized context notes file to be bounded",
        )
        self.soft_assert(
            system_text.count("Filler context note line") < 500,
            "Expected default context to truncate oversized context notes content",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
