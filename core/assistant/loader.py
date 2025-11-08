"""
Assistant configuration management with fully parsed objects.

Handles auto-discovery and loading of assistant files from vault directories,
storing parsed schedules and workflow functions instead of raw strings.
"""

import os
import importlib
import types
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime

from .parser import parse_assistant_file, validate_config
from .assistant import Assistant
from core.constants import CONTAINER_DATA_ROOT, VAULT_IGNORE_FILE
from core.scheduling.parser import parse_schedule_syntax
from core.scheduling.triggers import create_schedule_trigger
from core.logger import UnifiedLogger

# Create system logger for assistant configuration management
logger = UnifiedLogger(tag="assistant-loader")


#######################################################################
## Data Structures
#######################################################################

class ConfigurationError:
    """Represents a configuration error encountered during loading."""
    def __init__(self, vault: str, assistant_name: Optional[str], file_path: str,
                 error_message: str, error_type: str, timestamp: datetime):
        self.vault = vault
        self.assistant_name = assistant_name
        self.file_path = file_path
        self.error_message = error_message
        self.error_type = error_type
        self.timestamp = timestamp


#######################################################################
## Vault Discovery Interface
#######################################################################

@logger.trace("vault_discovery")
def discover_vaults(data_root: str = CONTAINER_DATA_ROOT) -> List[str]:
    """Return list of vault names from first-level directories, excluding ignored directories."""
    if not os.path.exists(data_root) or not os.path.isdir(data_root):
        return []

    vaults = []
    for item in os.listdir(data_root):
        item_path = os.path.join(data_root, item)
        if os.path.isdir(item_path):
            ignore_file = os.path.join(item_path, VAULT_IGNORE_FILE)
            if not os.path.exists(ignore_file):
                vaults.append(item)

    return sorted(vaults)


@logger.trace("assistant_file_discovery")
def discover_assistant_files(vault_path: str) -> List[str]:
    """Return list of assistant file paths in vault/assistants/ and subfolders (one level deep).

    Ignores folders prefixed with underscore (e.g., _chat-sessions).
    """
    assistants_dir = os.path.join(vault_path, "assistants")

    if not os.path.exists(assistants_dir) or not os.path.isdir(assistants_dir):
        return []

    assistant_files = []

    # Scan for .md files directly in assistants/
    for item in os.listdir(assistants_dir):
        item_path = os.path.join(assistants_dir, item)

        if item.endswith('.md') and os.path.isfile(item_path):
            # Direct file in assistants/
            assistant_files.append(item_path)
        elif os.path.isdir(item_path) and not item.startswith('_'):
            # Subfolder (not prefixed with underscore) - scan one level deep
            for subitem in os.listdir(item_path):
                if subitem.endswith('.md'):
                    subitem_path = os.path.join(item_path, subitem)
                    if os.path.isfile(subitem_path):
                        assistant_files.append(subitem_path)

    return sorted(assistant_files)


#######################################################################
## Assistant Loading Functions
#######################################################################

@logger.trace("workflow_loading")
def validate_and_load_workflow(workflow_name: str) -> tuple[types.ModuleType, Callable]:
    """Load and validate a workflow module and its run_workflow function.

    Args:
        workflow_name: Name of the workflow module

    Returns:
        Tuple of (workflow_module, workflow_function)

    Raises:
        ImportError: If workflow module cannot be imported
        AttributeError: If run_workflow function is not found in module
    """
    # Import the workflow module
    workflow_module = importlib.import_module(f"workflows.{workflow_name}.workflow")

    # Get the run_workflow function
    workflow_function = getattr(workflow_module, 'run_workflow')

    # Validate it's callable
    if not callable(workflow_function):
        raise AttributeError(f"'run_workflow' in workflow '{workflow_name}' is not callable")

    return workflow_module, workflow_function

@logger.trace("assistant_loading")
def load_assistant_from_file(file_path: str, vault: str, name: str,
                           validated_config: Dict[str, Any]) -> Assistant:
    """Load an Assistant from a parsed configuration.

    Args:
        file_path: Path to the assistant markdown file
        vault: Vault name
        name: Assistant name
        validated_config: Already validated configuration dictionary

    Returns:
        Assistant object with all parsed components
    """
    # Parse schedule if provided and create actual trigger
    trigger = None
    schedule_string = validated_config['schedule']  # Store original for display
    if schedule_string is not None:
        parsed_schedule = parse_schedule_syntax(schedule_string)
        trigger = create_schedule_trigger(parsed_schedule)

    # Load and validate workflow module
    workflow_name = validated_config['workflow']
    workflow_module, workflow_function = validate_and_load_workflow(workflow_name)

    # Create Assistant object
    assistant = Assistant(
        vault=vault,
        name=name,
        file_path=file_path,
        trigger=trigger,
        schedule_string=schedule_string,
        workflow_function=workflow_function,
        workflow_module=workflow_module,
        workflow_name=workflow_name,
        week_start_day=validated_config['week_start_day'],
        description=validated_config['description'],
        enabled=validated_config['enabled']
    )

    return assistant


#######################################################################
## Assistant Loader Manager
#######################################################################

class AssistantLoader:
    """
    Manages loading and validation of vault-based assistant configurations with parsed objects.

    WARNING: Direct instantiation is discouraged. Use RuntimeContext.assistant_loader instead
    to ensure proper dependency injection and avoid multiple instances.
    """

    def __init__(self, _data_root: str = CONTAINER_DATA_ROOT, *, _allow_direct_instantiation: bool = False):
        """
        Initialize the assistant loader.

        Args:
            _data_root: Root directory for vault data
            _allow_direct_instantiation: Internal flag to prevent accidental direct creation

        Raises:
            RuntimeError: If direct instantiation is attempted without permission
        """
        if not _allow_direct_instantiation:
            raise RuntimeError(
                "Direct AssistantLoader instantiation is discouraged. "
                "Use get_runtime_context().assistant_loader or bootstrap_runtime() instead."
            )
        self._data_root = _data_root
        self._assistants: List[Assistant] = []
        self._config_errors: List[ConfigurationError] = []
        self._last_loaded: Optional[datetime] = None
        self._vault_info: Dict[str, Dict[str, Any]] = {}  # Cache vault discovery data

    @logger.trace("assistant_loading")
    async def load_assistants(self, force_reload: bool = False, target_global_id: str = None) -> List[Assistant]:
        """Load assistants from all vaults or a specific assistant."""
        # Parse target if specified
        target_vault = None
        target_name = None
        if target_global_id:
            if '/' not in target_global_id:
                raise ValueError(f"Invalid target_global_id format. Expected 'vault/name', got: {target_global_id}")
            target_vault, target_name = target_global_id.split('/', 1)

        # Discover all vaults (or filter to target vault)
        vaults = discover_vaults(self._data_root)
        if target_vault:
            vaults = [target_vault] if target_vault in vaults else []
            if not vaults:
                raise ValueError(f"Target vault '{target_vault}' not found")

        if not vaults:
            if not target_global_id:
                self._assistants = []
                self._last_loaded = datetime.now()
            return []

        # Clear previous errors on full reload
        if not target_global_id:
            self._config_errors = []

        # Load assistant configurations from all vaults
        assistants = []
        global_ids = set()
        vault_info = {}

        for vault in vaults:
            vault_path = os.path.join(self._data_root, vault)
            assistant_files = discover_assistant_files(vault_path)

            # Cache vault info during processing
            vault_info[vault] = {
                'path': vault_path,
                'assistant_files': assistant_files,
                'assistants': []
            }

            for file_path in assistant_files:
                try:
                    # Extract vault and name from file path
                    # Expected formats:
                    #   - Direct: vault/assistants/daily.md -> name = 'daily'
                    #   - Subfolder: vault/assistants/planning/daily.md -> name = 'planning/daily'
                    path_parts = file_path.replace(self._data_root, '').strip('/').split('/')
                    if len(path_parts) < 3 or path_parts[1] != 'assistants':
                        continue

                    vault = path_parts[0]

                    # Handle both direct files and files in subfolders (one level deep)
                    if len(path_parts) == 3:
                        # Direct file: vault/assistants/filename.md
                        name = os.path.splitext(path_parts[2])[0]
                    elif len(path_parts) == 4:
                        # Subfolder file: vault/assistants/subfolder/filename.md
                        subfolder = path_parts[2]
                        filename = os.path.splitext(path_parts[3])[0]
                        name = f"{subfolder}/{filename}"
                    else:
                        # Unexpected path structure (too deep) - skip
                        continue

                    # Skip if targeting specific assistant and this isn't it
                    if target_name and name != target_name:
                        continue

                    # Parse assistant file using frontmatter format
                    sections = parse_assistant_file(file_path, f"{vault}/{name}")

                    # Extract configuration from frontmatter
                    raw_config = sections.get('__FRONTMATTER_CONFIG__', {})
                    if not raw_config:
                        raise ValueError("Missing YAML frontmatter configuration")

                    # Validate configuration from template/user file
                    validated_config = validate_config(raw_config, vault, name)

                    # Create Assistant object with parsed objects (not strings)
                    assistant = load_assistant_from_file(file_path, vault, name, validated_config)

                    # Check for global ID conflicts
                    if assistant.global_id in global_ids:
                        raise ValueError(f"Duplicate assistant global ID: {assistant.global_id}")
                    global_ids.add(assistant.global_id)

                    assistants.append(assistant)

                    # Add to vault cache
                    vault_info[vault]['assistants'].append(assistant.name)

                except Exception as e:
                    # Create configuration error record
                    config_error = ConfigurationError(
                        vault=vault,
                        assistant_name=name if 'name' in locals() else None,
                        file_path=file_path,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        timestamp=datetime.now()
                    )
                    self._config_errors.append(config_error)

                    vault_identifier = f"{vault}/{name}" if 'name' in locals() else vault
                    logger.activity(
                        f"Failed to load assistant file {file_path}: {str(e)}",
                        vault=vault_identifier,
                        level="error",
                        metadata={
                            "file_path": file_path,
                            "error_type": type(e).__name__,
                        },
                    )
                    # Continue with other files rather than failing completely
                    continue

        # Handle different modes of operation
        if target_global_id:
            # Single assistant mode - validate we found the target
            if not assistants:
                raise ValueError(f"Target assistant '{target_global_id}' not found")

            # Update the specific assistant in the cache
            target_assistant = assistants[0]

            # Remove old version from cache if it exists
            self._assistants = [assistant for assistant in self._assistants if assistant.global_id != target_global_id]
            self._assistants.append(target_assistant)

            return assistants
        else:
            # Full reload mode - replace entire cache
            self._assistants = assistants
            self._vault_info = vault_info
            self._last_loaded = datetime.now()
            return assistants

    def get_enabled_assistants(self) -> List[Assistant]:
        """Get only enabled assistant configurations."""
        return [assistant for assistant in self._assistants if assistant.enabled]

    def get_configuration_errors(self) -> List[ConfigurationError]:
        """Get list of configuration errors encountered during loading."""
        return self._config_errors.copy()

    def get_vault_info(self) -> Dict[str, Dict[str, Any]]:
        """Get cached vault discovery data."""
        return self._vault_info.copy()

    def get_assistant_by_global_id(self, global_id: str) -> Optional[Assistant]:
        """Get assistant configuration by global ID (vault/name format)."""
        for assistant in self._assistants:
            if assistant.global_id == global_id:
                return assistant
        return None

    async def ensure_assistant_directories(self, assistant: Assistant):
        """Ensure that the assistant's directories exist."""
        assistants_dir = os.path.dirname(assistant.file_path)
        os.makedirs(assistants_dir, exist_ok=True)


# Note: AssistantLoader instances should be created through RuntimeContext.
# Direct instantiation is discouraged to maintain proper dependency injection.
