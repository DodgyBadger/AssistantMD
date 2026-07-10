"""Integration scenario for file_read search across normal text files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from core.vault_state.file_operations import search_vault_files_operation
from validation.core.base_scenario import BaseScenario


class FileReadSearchTextFilesScenario(BaseScenario):
    """Validate search is not limited to markdown after all-file listing support."""

    async def test_scenario(self):
        vault = self.create_vault("FileReadSearchTextFilesVault")
        self.create_file(vault, "notes/alpha.md", "needle in markdown\n")
        self.create_file(vault, "notes/bravo.txt", "needle in text\n")
        self.create_file(vault, "notes/charlie.json", '{"value": "needle in json"}\n')
        self.create_file(vault, "notes/.hidden.txt", "needle hidden\n")
        self.create_file(vault, "notes/nomatch.txt", "nothing here\n")

        await self.start_system()

        broad = search_vault_files_operation(
            vault_path=str(vault),
            path="notes",
            search_term="needle",
        )
        broad_matches = set(broad.metadata.get("matches") or [])
        self.soft_assert_equal(
            broad.metadata.get("status"),
            "completed",
            "Search should complete across a directory of text files",
        )
        self.soft_assert(
            any(match.startswith("notes/alpha.md:") for match in broad_matches),
            "Search should include markdown matches",
        )
        self.soft_assert(
            any(match.startswith("notes/bravo.txt:") for match in broad_matches),
            "Search should include non-markdown text matches",
        )
        self.soft_assert(
            any(match.startswith("notes/charlie.json:") for match in broad_matches),
            "Search should include JSON text matches",
        )
        self.soft_assert(
            not any(".hidden.txt" in match for match in broad_matches),
            "Search should continue to exclude hidden files by default",
        )

        explicit_file = search_vault_files_operation(
            vault_path=str(vault),
            path="notes/bravo.txt",
            search_term="needle",
        )
        self.soft_assert(
            any(
                match.startswith("notes/bravo.txt:")
                for match in explicit_file.metadata.get("matches") or []
            ),
            "Search should work when scoped to an explicit non-markdown file",
        )

        explicit_glob = search_vault_files_operation(
            vault_path=str(vault),
            path="notes/*.txt",
            search_term="needle",
        )
        glob_matches = set(explicit_glob.metadata.get("matches") or [])
        self.soft_assert(
            any(match.startswith("notes/bravo.txt:") for match in glob_matches),
            "Explicit glob search should keep matching non-markdown text files",
        )
        self.soft_assert(
            not any(match.startswith("notes/alpha.md:") for match in glob_matches),
            "Explicit glob search should respect the caller's file pattern",
        )

        miss = search_vault_files_operation(
            vault_path=str(vault),
            path="notes",
            search_term="absent",
        )
        self.soft_assert_equal(
            miss.return_value,
            "No matches found for 'absent' in text files",
            "No-match message should describe the all-text search scope",
        )

        await self.stop_system()
        self.teardown_scenario()
        self.assert_no_failures()
