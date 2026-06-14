"""Integration scenario for extensionless markdown text mutations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.tools.file_ops_unsafe import FileOpsUnsafe
from validation.core.base_scenario import BaseScenario


class FileOpsExtensionlessTextMutationsScenario(BaseScenario):
    """Validate unsafe text mutations use markdown-first extensionless resolution."""

    async def test_scenario(self):
        vault = self.create_vault("FileOpsExtensionlessTextMutationsVault")
        self.create_file(vault, "notes/edit-target.md", "first\nreplace me\nlast\n")
        self.create_file(vault, "notes/no-extension", "alpha\n")
        self.create_file(vault, "notes/crlf-target.md", "first\r\nreplace me\r\nlast\r\n")

        await self.start_system()

        edited = FileOpsUnsafe._edit_line(
            "notes/edit-target",
            2,
            "replace me",
            "changed",
            str(vault),
        )
        self.soft_assert_equal(
            edited.metadata.get("status"),
            "completed",
            "Extensionless edit_line should resolve to the existing markdown file",
        )
        self.soft_assert_equal(
            edited.metadata.get("path"),
            "notes/edit-target.md",
            "edit_line metadata should report the effective markdown path",
        )
        self.soft_assert_equal(
            edited.metadata.get("requested_path"),
            "notes/edit-target",
            "edit_line metadata should preserve the requested extensionless path",
        )
        self.soft_assert_equal(
            (vault / "notes" / "edit-target.md").read_text(encoding="utf-8"),
            "first\nchanged\nlast\n",
            "edit_line should mutate the markdown file selected by extensionless resolution",
        )
        crlf_edit = FileOpsUnsafe._edit_line(
            "notes/crlf-target.md",
            2,
            "replace me",
            "changed",
            str(vault),
        )
        self.soft_assert_equal(
            crlf_edit.metadata.get("status"),
            "completed",
            "edit_line should compare CRLF lines without requiring a trailing carriage return",
        )
        self.soft_assert_equal(
            (vault / "notes" / "crlf-target.md").read_bytes(),
            b"first\r\nchanged\r\nlast\r\n",
            "edit_line should preserve CRLF line endings when replacing a line",
        )

        replaced = FileOpsUnsafe._replace_text(
            "notes/edit-target",
            "changed",
            "done",
            1,
            str(vault),
        )
        self.soft_assert_equal(
            replaced.metadata.get("path"),
            "notes/edit-target.md",
            "replace_text metadata should report the effective markdown path",
        )
        self.soft_assert_equal(
            (vault / "notes" / "edit-target.md").read_text(encoding="utf-8"),
            "first\ndone\nlast\n",
            "replace_text should mutate the markdown file selected by extensionless resolution",
        )

        truncated = FileOpsUnsafe._truncate_file(
            "notes/edit-target",
            "notes/edit-target",
            str(vault),
        )
        self.soft_assert_equal(
            truncated.metadata.get("path"),
            "notes/edit-target.md",
            "truncate metadata should report the effective markdown path",
        )
        self.soft_assert_equal(
            (vault / "notes" / "edit-target.md").read_text(encoding="utf-8"),
            "",
            "truncate should clear the markdown file selected by extensionless resolution",
        )

        fallback = FileOpsUnsafe._replace_text(
            "notes/no-extension",
            "alpha",
            "beta",
            1,
            str(vault),
        )
        self.soft_assert_equal(
            fallback.metadata.get("path"),
            "notes/no-extension",
            "Extensionless fallback should still allow an existing no-extension target when no .md file exists",
        )
        self.soft_assert_equal(
            (vault / "notes" / "no-extension").read_text(encoding="utf-8"),
            "beta\n",
            "Extensionless fallback should mutate the original target when no markdown sibling exists",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
