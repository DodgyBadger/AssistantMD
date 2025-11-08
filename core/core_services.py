"""
Core services interface for workflow development.

Provides a unified interface for workflows to access core system services,
eliminating the need to import and understand multiple core modules.
Solves global constant dependencies and simplifies workflow development.
"""

import os
from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

from core.constants import CONTAINER_DATA_ROOT
from core.runtime.state import get_runtime_context
from core.assistant.parser import (
    parse_assistant_file,
    get_workflow_sections,
    process_step_content,
)
from core.llm.agents import generate_response, create_agent
from core.directives.registry import register_directive
from core.directives.base import DirectiveProcessor
from core.directives.file_state import AssistantFileStateManager


@dataclass
class CoreServices:
    """
    Unified interface for workflow development.
    
    Provides workflows with access to essential core services using global_id
    as the primary interface. Automatically resolves all configuration from
    the global_id, eliminating the need for complex parameter construction.
    
    Attributes:
        global_id: Assistant identifier (format: 'vault/name') 
        _data_root: Root path for all vault data (defaults to CONTAINER_DATA_ROOT)
        
    Computed Properties (resolved automatically):
        vault_name: Name of the vault (e.g., 'HaikuVault')
        assistant_file_path: Path to the assistant markdown file
        week_start_day: Week start day number (0=Monday, 6=Sunday)
        assistant_id: Assistant identifier (same as global_id)
        vault_path: Full path to the vault directory
    """
    
    global_id: str
    _data_root: str = field(default_factory=lambda: CONTAINER_DATA_ROOT)
    
    # Computed properties (resolved in __post_init__)
    vault_name: str = field(init=False)
    assistant_file_path: str = field(init=False)
    week_start_day: int = field(init=False)
    assistant_id: str = field(init=False)
    vault_path: str = field(init=False)
    
    def __post_init__(self):
        """Resolve all parameters from global_id and initialize services."""
        # Validate global_id format
        if '/' not in self.global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {self.global_id}")
        
        # Parse global_id
        vault_name, assistant_name = self.global_id.split('/', 1)
        self.vault_name = vault_name
        self.assistant_id = self.global_id
        
        # Construct paths
        self.vault_path = os.path.join(self._data_root, vault_name)
        self.assistant_file_path = os.path.join(self.vault_path, "assistants", f"{assistant_name}.md")
        
        # Resolve week_start_day from assistant config
        self.week_start_day = self._resolve_week_start_day()
        
        # Initialize state manager
        self._state_manager = AssistantFileStateManager(self.vault_name, self.assistant_id)
    
    def _resolve_week_start_day(self) -> int:
        """Resolve week_start_day from runtime context assistant_loader."""
        runtime = get_runtime_context()
        assistant = runtime.assistant_loader.get_assistant_by_global_id(self.global_id)
        if assistant:
            return assistant.week_start_day_number

        # If assistant not found, default to Monday
        return 1
    
    def get_assistant_sections(self) -> Dict[str, str]:
        """
        Load and parse assistant file sections.
        
        Parses the assistant markdown file and returns all workflow sections
        (excluding reserved sections like INSTRUCTIONS and __FRONTMATTER_CONFIG__).
        
        Returns:
            Dictionary mapping section names to content
            
        Raises:
            ValueError: If assistant file cannot be parsed
            FileNotFoundError: If assistant file does not exist
        """
        if not os.path.exists(self.assistant_file_path):
            raise FileNotFoundError(f"Assistant file not found: {self.assistant_file_path}")
        
        sections = parse_assistant_file(self.assistant_file_path)
        return get_workflow_sections(sections)
    
    def process_step(self, content: str, reference_date: Optional[datetime] = None, **context) -> Any:
        """
        Process step content through directive system.
        
        Parses and processes all @directives in the step content, resolving patterns
        and returning processed configuration along with cleaned content.
        
        Args:
            content: Raw step content with @directives
            reference_date: Reference date for time pattern resolution (defaults to now)
            **context: Additional context for directive processing
            
        Returns:
            ProcessedStep with clean content and processed directive configuration
            
        Raises:
            ValueError: If directive processing fails
        """
        if reference_date is None:
            reference_date = datetime.now()
            
        return process_step_content(
            step_content=content,
            vault_path=self.vault_path,
            reference_date=reference_date,
            week_start_day=self.week_start_day,
            state_manager=self._state_manager
        )
    
    async def create_agent(self, instructions: str, model=None, tools=None):
        """
        Create a Pydantic AI agent with instructions, model, and tools.
        
        Convenience method that wraps the core create_agent function with
        proper parameter handling for workflow development.
        
        Args:
            instructions: System instructions for the agent
            model: Optional model instance (from @model directive processing)
            tools: Optional list of tool functions (from @tools directive processing)
            
        Returns:
            Configured Pydantic AI agent instance
            
        Raises:
            Exception: If agent creation fails
        """
        return await create_agent(instructions, model, tools)
    
    async def generate_response(self, agent, prompt: str, message_history=None) -> str:
        """
        Generate LLM response using a pre-configured agent.
        
        The agent should be created by the workflow after processing @model and @tools directives.
        
        Args:
            agent: Pre-configured Pydantic AI agent instance
            prompt: Input prompt for the LLM
            message_history: Optional message history for conversation
            
        Returns:
            Generated response text
            
        Raises:
            Exception: If LLM generation fails
        """
        return await generate_response(agent, prompt, message_history)
    
    def register_directive(self, processor: DirectiveProcessor) -> None:
        """
        Register a custom directive processor.
        
        Convenience method for workflows to register custom @directives
        without needing to import the global registry.
        
        Args:
            processor: The directive processor to register
            
        Raises:
            DuplicateDirectiveError: If directive is already registered
        """
        register_directive(processor)
    
    def get_vault_relative_path(self, path: str) -> str:
        """
        Get full path relative to vault root.
        
        Helper method for resolving paths within vault boundaries.
        
        Args:
            path: Relative path from vault root
            
        Returns:
            Full path resolved from vault root
        """
        return os.path.join(self.vault_path, path)
    
    def get_state_manager(self) -> AssistantFileStateManager:
        """
        Get the file state manager for this workflow execution.
        
        Provides access to state tracking for stateful directives like {pending}.
        
        Returns:
            AssistantFileStateManager instance for this vault and assistant
        """
        return self._state_manager
