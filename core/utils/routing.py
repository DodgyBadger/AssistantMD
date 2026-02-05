"""
Shared routing helpers for directive/tool outputs.

Provides parsing for output targets, write-mode normalization,
and a single write path for buffers/files.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Optional

from core.directives.output import OutputFileDirective
from core.directives.write_mode import WriteModeDirective
from core.runtime.buffers import get_buffer_store_for_scope


@dataclass(frozen=True)
class OutputTarget:
    type: str  # inline | discard | buffer | file
    name: Optional[str] = None
    path: Optional[str] = None


def normalize_write_mode(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return WriteModeDirective().process_value(value, vault_path="")


def parse_output_target(
    value: Any,
    vault_path: str,
    *,
    reference_date=None,
    week_start_day: int = 0,
) -> OutputTarget:
    if isinstance(value, dict):
        if value.get("type") == "inline":
            return OutputTarget(type="inline")
        if value.get("type") == "discard":
            return OutputTarget(type="discard")
        if "buffer" in value:
            return OutputTarget(type="buffer", name=value.get("buffer"))
        if "file" in value:
            return OutputTarget(type="file", path=value.get("file"))
        if value.get("type") == "buffer":
            return OutputTarget(type="buffer", name=value.get("name"))
        if value.get("type") == "file":
            return OutputTarget(type="file", path=value.get("path"))
        raise ValueError(f"Unsupported output target dict: {value}")

    if not value or not str(value).strip():
        raise ValueError("Output target cannot be empty")
    normalized = str(value).strip()
    lowered = normalized.lower()
    if lowered == "inline":
        return OutputTarget(type="inline")
    if lowered == "discard":
        return OutputTarget(type="discard")

    directive = OutputFileDirective()
    result = directive.process_value(
        normalized,
        vault_path,
        reference_date=reference_date,
        week_start_day=week_start_day,
    )
    if isinstance(result, dict) and result.get("type") == "buffer":
        return OutputTarget(type="buffer", name=result.get("name"))
    if isinstance(result, str):
        return OutputTarget(type="file", path=result)
    raise ValueError(f"Unsupported output target: {value}")


def build_manifest(
    *,
    source: str,
    destination: str,
    item_count: Optional[int] = None,
    total_chars: Optional[int] = None,
    paths: Optional[list[str]] = None,
    note: Optional[str] = None,
) -> str:
    lines = [f"[output routed] {source} -> {destination}"]
    if item_count is not None or total_chars is not None:
        details = []
        if item_count is not None:
            details.append(f"items: {item_count}")
        if total_chars is not None:
            details.append(f"chars: {total_chars}")
        lines.append(", ".join(details))
    if paths:
        lines.append("paths: " + ", ".join(paths))
    if note:
        lines.append(note)
    return "\n".join(lines)


def format_input_files_block(
    input_file_data: Any,
    *,
    has_empty_directive: bool = False,
) -> Optional[str]:
    if not input_file_data and not has_empty_directive:
        return None

    def _normalize_input_file_lists(data: Any) -> list[list[dict[str, Any]]]:
        if not data:
            return []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return [data]
        if isinstance(data, list):
            return data
        return []

    file_lists = _normalize_input_file_lists(input_file_data)
    if not file_lists and not has_empty_directive:
        return None

    flattened_files: list[dict[str, Any]] = []
    for file_list in file_lists:
        flattened_files.extend(file_list)

    formatted_content: list[str] = []
    path_only_entries: list[str] = []
    manifest_entries: list[str] = []
    for file_data in flattened_files:
        if not isinstance(file_data, dict):
            continue
        if file_data.get("manifest"):
            manifest_entries.append(file_data.get("manifest"))
            continue
        if file_data.get("refs_only"):
            label = f"- {file_data.get('filepath', 'unknown')}"
            if not file_data.get("found", True):
                error_msg = file_data.get("error", "File not found")
                label += f" (missing: {error_msg})"
            path_only_entries.append(label)
        elif file_data.get("found") and file_data.get("content"):
            formatted_content.append(
                f"--- FILE: {file_data.get('filepath', 'unknown')} ---\n{file_data.get('content', '')}"
            )
        elif file_data.get("found") is False:
            formatted_content.append(
                f"--- FILE: {file_data.get('filepath', 'unknown')} ---\n[FILE NOT FOUND: {file_data.get('error')}]"
            )

    if not path_only_entries and not formatted_content and not manifest_entries:
        if has_empty_directive:
            return "\n".join(
                [
                    "=== BEGIN INPUT_FILES ===",
                    "--- FILE PATHS (CONTENT NOT INLINED) ---",
                    "[NO INPUT FILES SPECIFIED IN TEMPLATE]",
                    "=== END INPUT_FILES ===",
                ]
            )
        return None

    sections: list[str] = []
    sections.append("=== BEGIN INPUT_FILES ===")
    if manifest_entries:
        sections.append("--- ROUTED INPUTS ---")
        sections.append("\n".join(manifest_entries))
    if path_only_entries:
        sections.append("--- FILE PATHS (CONTENT NOT INLINED) ---")
        sections.append("\n".join(path_only_entries))
    if formatted_content:
        sections.append("\n\n".join(formatted_content))
    sections.append("=== END INPUT_FILES ===")

    return "\n".join(sections)


def _generate_numbered_file_path(full_file_path: str, vault_path: str) -> str:
    if full_file_path.startswith(vault_path + "/"):
        relative_path = full_file_path[len(vault_path) + 1:]
    else:
        relative_path = full_file_path

    if relative_path.endswith(".md"):
        base_path = relative_path[:-3]
    else:
        base_path = relative_path

    directory = os.path.dirname(base_path) if os.path.dirname(base_path) else "."
    basename = os.path.basename(base_path)
    full_directory = os.path.join(vault_path, directory)

    existing_numbers = set()
    if os.path.exists(full_directory):
        for filename in os.listdir(full_directory):
            if filename.startswith(f"{basename}_") and filename.endswith(".md"):
                number_part = filename[len(basename) + 1 : -3]
                try:
                    number = int(number_part)
                    existing_numbers.add(number)
                except ValueError:
                    continue

    next_number = 0
    while next_number in existing_numbers:
        next_number += 1

    numbered_relative_path = f"{base_path}_{next_number:03d}.md"
    return f"{vault_path}/{numbered_relative_path}"


def _generate_numbered_buffer_name(base_name: str, buffer_store) -> str:
    existing = set(buffer_store.list().keys()) if buffer_store else set()
    next_number = 0
    candidate = f"{base_name}_{next_number:03d}"
    while candidate in existing:
        next_number += 1
        candidate = f"{base_name}_{next_number:03d}"
    return candidate


def write_output(
    *,
    target: OutputTarget,
    content: str,
    write_mode: Optional[str],
    buffer_store=None,
    buffer_store_registry=None,
    vault_path: Optional[str] = None,
    header: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    buffer_scope: Optional[str] = None,
    default_scope: str = "run",
) -> dict[str, Any]:
    mode = write_mode or "append"
    if target.type == "inline":
        return {"routed": False, "type": "inline"}
    if target.type == "discard":
        return {"routed": True, "type": "discard"}

    if target.type == "buffer":
        resolved_store = get_buffer_store_for_scope(
            scope=buffer_scope,
            default_scope=default_scope,
            buffer_store=buffer_store,
            buffer_store_registry=buffer_store_registry,
        )
        if resolved_store is None:
            raise ValueError("Buffer store unavailable for variable output")
        name = target.name or "output"
        if mode == "new":
            name = _generate_numbered_buffer_name(name, resolved_store)
            mode_to_use = "replace"
        elif mode == "replace":
            mode_to_use = "replace"
        else:
            mode_to_use = "append"
        buffer_metadata = {"source": "routing"}
        if metadata:
            buffer_metadata.update(metadata)
        resolved_store.put(name, content or "", mode=mode_to_use, metadata=buffer_metadata)
        return {"routed": True, "type": "buffer", "name": name, "write_mode": mode_to_use, "output_length": len(content or "")}

    if target.type == "file":
        if not vault_path:
            raise ValueError("vault_path is required for file output")
        output_file = os.path.join(vault_path, target.path or "")
        if mode == "new":
            output_file = _generate_numbered_file_path(output_file, vault_path)
            file_mode = "w"
        elif mode == "replace":
            file_mode = "w"
        else:
            file_mode = "a"

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, file_mode, encoding="utf-8") as file:
            if header:
                file.write(f"# {header}\n\n")
            file.write(content or "")
            file.write("\n\n")
        return {"routed": True, "type": "file", "path": output_file, "write_mode": mode, "output_length": len(content or "")}

    raise ValueError(f"Unknown output target type: {target.type}")
