"""Portable process and cgroup resource observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CgroupMemoryStatus:
    """Current cgroup v2 memory usage and limits when available."""

    current_bytes: int | None
    max_bytes: int | None
    events: dict[str, int] = field(default_factory=dict)

    @property
    def available_bytes(self) -> int | None:
        if self.current_bytes is None or self.max_bytes is None:
            return None
        return max(0, self.max_bytes - self.current_bytes)


def read_cgroup_memory_status(
    root: Path = Path("/sys/fs/cgroup"),
) -> CgroupMemoryStatus:
    """Read cgroup v2 memory files without assuming containerization."""
    current = _read_int(root / "memory.current")
    maximum = _read_limit(root / "memory.max")
    events = _read_events(root / "memory.events")
    return CgroupMemoryStatus(
        current_bytes=current,
        max_bytes=maximum,
        events=events,
    )


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_limit(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _read_events(path: Path) -> dict[str, int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    events: dict[str, int] = {}
    for line in lines:
        key, separator, raw_value = line.partition(" ")
        if not separator:
            continue
        try:
            events[key] = int(raw_value.strip())
        except ValueError:
            continue
    return events
