"""
WorkflowDefinition captures parsed workflow metadata for scheduling and execution.

This replaces the older AssistantConfig naming to better align with documentation.
"""

import os
import types
from typing import Optional, Callable
from apscheduler.triggers.base import BaseTrigger
from dataclasses import dataclass

from core.constants import CONTAINER_DATA_ROOT


@dataclass
class WorkflowDefinition:
    """Workflow configuration with fully parsed and validated objects."""
    vault: str
    name: str
    file_path: str
    trigger: Optional[BaseTrigger]       # APScheduler trigger object, None for manual-only
    schedule_string: Optional[str]       # Original schedule string from config (for display)
    workflow_function: Callable          # Loaded workflow function
    workflow_module: types.ModuleType   # Cached module reference
    workflow_name: str                  # Original workflow name string
    week_start_day: str
    description: str
    enabled: bool = True

    @property
    def global_id(self) -> str:
        """Return vault/name format for unique identification."""
        return f"{self.vault}/{self.name}"

    @property
    def vault_path(self) -> str:
        """Return full vault directory path."""
        return os.path.join(CONTAINER_DATA_ROOT, self.vault)

    @property
    def scheduler_job_id(self) -> str:
        """Return scheduler-safe job ID (using global_id with safe characters)."""
        return self.global_id.replace("/", "__")

    @property
    def week_start_day_number(self) -> int:
        """Get the week start day as a number (0=Monday, 6=Sunday)."""
        day_mapping = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        return day_mapping[self.week_start_day]


