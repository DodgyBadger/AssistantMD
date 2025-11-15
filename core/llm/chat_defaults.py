"""
Default configuration for chat execution when saving as steps.

Tools and model are user-selected via UI, not hardcoded.
"""

from dataclasses import dataclass


@dataclass
class ChatExecutionDefaults:
    """
    Defaults for dynamic chat execution when saving as steps.

    These values are used for workflow file creation but not for
    execution itself - execution uses user-selected tools and model.
    """
    run_on: str = "never"
    write_mode: str = "append"
    enabled: bool = False  # Dynamic workflows created via chat are never scheduled
