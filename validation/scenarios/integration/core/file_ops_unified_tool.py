"""Validate split file_read and file_write tool contracts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.authoring.helpers.runtime_common import invoke_bound_tool, normalize_tool_result
from core.authoring.shared.tool_binding import resolve_tool_binding
from validation.core.base_scenario import BaseScenario


class FileOpsUnifiedToolScenario(BaseScenario):
    """Validate file_read/file_write expose the v0.7.0 command-style contract."""

    async def test_scenario(self) -> None:
        vault = self.create_vault("FileOpsUnifiedToolVault")
        self.create_file(vault, "notes/source.md", "one\ntwo\nthree\nfour\n")
        self.create_file(vault, "notes/edit.md", "Alpha beta alpha\n")

        await self.start_system()
        try:
            binding = resolve_tool_binding(["file_read", "file_write"], vault_path=str(vault))
            assert binding.tool_names() == ["file_read", "file_write"]
            read_tool = binding.tool_functions[0]
            write_tool = binding.tool_functions[1]

            read_range = await self._call(read_tool, vault, "file_read", {
                "operation": "read",
                "path": "notes/source.md",
                "start_line": 2,
                "line_count": 2,
            })
            assert read_range.return_value == "two\nthree"
            assert read_range.metadata["tool_name"] == "file_read"
            assert read_range.metadata["operation"] == "read"
            assert read_range.metadata["start_line"] == 2
            assert read_range.metadata["lines_returned"] == 2

            listed = await self._call(read_tool, vault, "file_read", {
                "operation": "list",
                "path": "notes",
            })
            assert listed.metadata["status"] == "completed"
            assert "notes/source.md" in listed.metadata["files"]

            searched = await self._call(read_tool, vault, "file_read", {
                "operation": "search",
                "path": "notes",
                "search_term": "two",
            })
            assert searched.metadata["status"] == "completed"
            assert searched.metadata["match_count"] >= 1

            created = await self._call(write_tool, vault, "file_write", {
                "operation": "write",
                "path": "notes/new.md",
                "content": "Created\n",
            })
            assert created.metadata["status"] == "completed"
            assert (vault / "notes/new.md").read_text(encoding="utf-8") == "Created\n"

            duplicate = await self._call(write_tool, vault, "file_write", {
                "operation": "write",
                "path": "notes/new.md",
                "content": "No overwrite\n",
            })
            assert duplicate.metadata["status"] == "already_exists"
            assert duplicate.metadata["error_type"] == "file_exists"
            assert (vault / "notes/new.md").read_text(encoding="utf-8") == "Created\n"

            blank_path = await self._call(write_tool, vault, "file_write", {
                "operation": "write",
                "path": "  ",
                "content": "No path\n",
                "overwrite": True,
            })
            assert blank_path.metadata["status"] == "error"
            assert blank_path.metadata["error_type"] == "invalid_path"

            overwritten = await self._call(write_tool, vault, "file_write", {
                "operation": "write",
                "path": "notes/new.md",
                "content": "Overwritten\n",
                "overwrite": True,
            })
            assert overwritten.metadata["status"] == "completed"
            assert overwritten.metadata["overwrote"] is True
            assert (vault / "notes/new.md").read_text(encoding="utf-8") == "Overwritten\n"

            appended = await self._call(write_tool, vault, "file_write", {
                "operation": "append",
                "path": "notes/new.md",
                "content": "Appended\n",
            })
            assert appended.metadata["status"] == "completed"
            assert (vault / "notes/new.md").read_text(encoding="utf-8") == "Overwritten\nAppended\n"

            replaced = await self._call(write_tool, vault, "file_write", {
                "operation": "replace_text",
                "path": "notes/edit.md",
                "old_text": "Alpha",
                "new_text": "Gamma",
                "count": 1,
            })
            assert replaced.metadata["status"] == "completed"
            assert replaced.metadata["replacement_count"] == 1
            assert (vault / "notes/edit.md").read_text(encoding="utf-8") == "Gamma beta alpha\n"

            moved = await self._call(write_tool, vault, "file_write", {
                "operation": "move",
                "path": "notes/new.md",
                "destination": "archive/new.md",
            })
            assert moved.metadata["status"] == "completed"
            assert not (vault / "notes/new.md").exists()
            assert (vault / "archive/new.md").exists()

            made_directory = await self._call(write_tool, vault, "file_write", {
                "operation": "mkdir",
                "path": "empty/sub",
            })
            assert made_directory.metadata["status"] == "completed"
            assert (vault / "empty/sub").is_dir()

            batch = await self._call(write_tool, vault, "file_write", {
                "operation": "batch",
                "operations": [
                    {
                        "operation": "write",
                        "path": "batch/one.md",
                        "content": "One\n",
                    },
                    {
                        "operation": "write",
                        "path": "batch/two.md",
                        "content": "Two\n",
                    },
                    {
                        "operation": "move",
                        "path": "batch/two.md",
                        "destination": "batch/archive/two.md",
                    },
                ],
            })
            assert batch.metadata["status"] == "completed"
            assert batch.metadata["completed"] == 3
            assert batch.metadata["failed"] == 0
            assert len(batch.metadata["results"]) == 3
            assert (vault / "batch/one.md").read_text(encoding="utf-8") == "One\n"
            assert (vault / "batch/archive/two.md").read_text(encoding="utf-8") == "Two\n"

            invalid_batch = await self._call(write_tool, vault, "file_write", {
                "operation": "batch",
                "operations": [
                    {
                        "operation": "read",
                        "path": "batch/one.md",
                    },
                    {
                        "operation": "delete",
                        "path": "missing.md",
                        "confirm_path": "missing.md",
                    },
                ],
            })
            assert invalid_batch.metadata["status"] == "error"
            assert invalid_batch.metadata["error_type"] == "invalid_batch_operation"
            assert invalid_batch.metadata["completed"] == 0

            deleted = await self._call(write_tool, vault, "file_write", {
                "operation": "delete",
                "path": "archive/new.md",
                "confirm_path": "archive/new.md",
            })
            assert deleted.metadata["status"] == "completed"
            assert not (vault / "archive/new.md").exists()
        finally:
            await self.stop_system()
            self.teardown_scenario()

    async def _call(self, tool, vault: Path, tool_name: str, arguments: dict):
        result = await invoke_bound_tool(
            tool,
            tool_name=tool_name,
            arguments=arguments,
            run_buffers={},
            session_buffers={},
            session_id="file_ops_unified_tool",
            vault_name=vault.name,
        )
        return normalize_tool_result(tool_name, result, vault_path=str(vault))
