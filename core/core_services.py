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

from core.constants import ASSISTANTMD_ROOT_DIR, WORKFLOW_DEFINITIONS_DIR
from core.runtime.paths import get_data_root
from core.runtime.state import get_runtime_context
from core.workflow.parser import (
    parse_workflow_file,
    get_workflow_sections,
    process_step_content,
)
from core.llm.agents import generate_response, create_agent
from core.directives.registry import register_directive
from core.directives.base import DirectiveProcessor
from core.utils.file_state import WorkflowFileStateManager


@dataclass
class CoreServices:
    """
    Unified interface for workflow development.
    
    Provides workflows with access to essential core services using global_id
    as the primary interface. Automatically resolves all configuration from
    the global_id, eliminating the need for complex parameter construction.
    
    Attributes:
        global_id: Workflow identifier (format: 'vault/name') 
        _data_root: Root path for all vault data (defaults to data root helper)
        
    Computed Properties (resolved automatically):
        vault_name: Name of the vault (e.g., 'HaikuVault')
        workflow_file_path: Path to the workflow markdown file
        week_start_day: Week start day number (0=Monday, 6=Sunday)
        workflow_id: Workflow identifier (same as global_id)
        vault_path: Full path to the vault directory
    """
    
    global_id: str
    _data_root: str = field(default_factory=lambda: str(get_data_root()))
    
    # Computed properties (resolved in __post_init__)
    vault_name: str = field(init=False)
    workflow_file_path: str = field(init=False)
    week_start_day: int = field(init=False)
    workflow_id: str = field(init=False)
    vault_path: str = field(init=False)
    
    def __post_init__(self):
        """Resolve all parameters from global_id and initialize services."""
        # Validate global_id format
        if '/' not in self.global_id:
            raise ValueError(f"Invalid global_id format. Expected 'vault/name', got: {self.global_id}")
        
        # Parse global_id
        vault_name, workflow_name = self.global_id.split('/', 1)
        self.vault_name = vault_name
        self.workflow_id = self.global_id
        
        # Construct paths
        self.vault_path = os.path.join(self._data_root, vault_name)
        self.workflow_file_path = os.path.join(
            self.vault_path,
            ASSISTANTMD_ROOT_DIR,
            WORKFLOW_DEFINITIONS_DIR,
            f"{workflow_name}.md"
        )
        
        # Resolve week_start_day from workflow config
        self.week_start_day = self._resolve_week_start_day()
        
        # Initialize state manager
        self._state_manager = WorkflowFileStateManager(self.vault_name, self.workflow_id)
    
    def _resolve_week_start_day(self) -> int:
        """Resolve week_start_day from runtime context workflow_loader."""
        runtime = get_runtime_context()
        workflow = runtime.workflow_loader.get_workflow_by_global_id(self.global_id)
        if workflow:
            return workflow.week_start_day_number

        # If workflow not found, default to Monday
        return 1
    
    def get_workflow_sections(self) -> Dict[str, str]:
        """
        Load and parse workflow file sections.
        
        Parses the workflow markdown file and returns all workflow sections
        (excluding reserved sections like INSTRUCTIONS and __FRONTMATTER_CONFIG__).
        
        Returns:
            Dictionary mapping section names to content
            
        Raises:
            ValueError: If workflow file cannot be parsed
            FileNotFoundError: If workflow file does not exist
        """
        if not os.path.exists(self.workflow_file_path):
            raise FileNotFoundError(f"Workflow file not found: {self.workflow_file_path}")
        
        sections = parse_workflow_file(self.workflow_file_path)
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
            state_manager=self._state_manager,
            buffer_store=context.get("buffer_store"),
        )
    
    async def create_agent(self, model=None, tools=None, history_processors=None):
        """
        Create a Pydantic AI agent with model and tools.

        Convenience method that wraps the core create_agent function with
        proper parameter handling for workflow development.

        Args:
            model: Optional model instance (from @model directive processing)
            tools: Optional list of tool functions (from @tools directive processing)

        Returns:
            Configured Pydantic AI agent instance

        Raises:
            Exception: If agent creation fails
        """
        return await create_agent(model=model, tools=tools, history_processors=history_processors)
    
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
    
    def get_state_manager(self) -> WorkflowFileStateManager:
        """
        Get the file state manager for this workflow execution.
        
        Provides access to state tracking for stateful directives like {pending}.
        
        Returns:
            WorkflowFileStateManager instance for this vault and workflow
        """
        return self._state_manager
