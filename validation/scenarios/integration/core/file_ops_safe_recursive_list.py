"""Validate recursive root listings in file_ops_safe."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.tools.file_ops_safe import FileOpsSafe
from validation.core.base_scenario import BaseScenario


class FileOpsSafeRecursiveListScenario(BaseScenario):
    """Validate recursive listing descends from root paths."""

    async def test_scenario(self):
        vault = self.create_vault("FileOpsSafeRecursiveListVault")
        self.create_file(vault, "top.md", "top\n")
        self.create_file(vault, "projects/alpha/note.md", "alpha\n")
        self.create_file(vault, "projects/beta/nested/task.txt", "task\n")

        await self.start_system()

        root_listing = FileOpsSafe._list_files(
            "",
            str(vault),
            recursive=True,
            max_results=200,
        )
        root_files = set(root_listing.metadata.get("files") or [])
        root_directories = set(root_listing.metadata.get("directories") or [])
        self.soft_assert(
            "projects/alpha/note.md" in root_files,
            "Recursive root listing should include nested files",
        )
        self.soft_assert(
            "projects/beta/nested/task.txt" in root_files,
            "Recursive root listing should include deeply nested files",
        )
        self.soft_assert(
            {"projects", "projects/alpha", "projects/beta", "projects/beta/nested"}.issubset(
                root_directories
            ),
            "Recursive root listing should include nested directories",
        )

        dot_listing = FileOpsSafe._list_files(
            ".",
            str(vault),
            recursive=True,
            max_results=200,
        )
        self.soft_assert_equal(
            dot_listing.metadata.get("files"),
            root_listing.metadata.get("files"),
            "Recursive '.' listing should match recursive root listing",
        )

        docs_listing = FileOpsSafe._list_virtual_mount(
            "__virtual_docs__",
            recursive=True,
            max_results=500,
        )
        self.soft_assert(
            "__virtual_docs__/tools/file_ops_safe.md"
            in set(docs_listing.metadata.get("files") or []),
            "Recursive virtual mount root listing should include nested docs",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
