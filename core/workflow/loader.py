"""
Workflow definition management with fully parsed objects.

Handles auto-discovery and loading of workflow files from vault directories,
storing parsed schedules and workflow engine references instead of raw strings.
"""

import os
import importlib
import types
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime

from .parser import parse_workflow_file, validate_config
from .definition import WorkflowDefinition
from core.constants import (
    VAULT_IGNORE_FILE,
    ASSISTANTMD_ROOT_DIR,
    WORKFLOW_DEFINITIONS_DIR,
    IMPORT_DIR,
    CONTEXT_TEMPLATE_DIR,
)
from core.runtime.paths import get_data_root
from core.scheduling.parser import parse_schedule_syntax
from core.scheduling.triggers import create_schedule_trigger
from core.logger import UnifiedLogger

# Create system logger for workflow configuration management
logger = UnifiedLogger(tag="workflow-loader")


#######################################################################
## Data Structures
#######################################################################

class ConfigurationError:
    """Represents a configuration error encountered during loading."""
    def __init__(self, vault: str, workflow_name: Optional[str], file_path: str,
                 error_message: str, error_type: str, timestamp: datetime):
        self.vault = vault
        self.workflow_name = workflow_name
        self.file_path = file_path
        self.error_message = error_message
        self.error_type = error_type
        self.timestamp = timestamp


#######################################################################
## Vault Discovery Interface
#######################################################################

@logger.trace("vault_discovery")
def discover_vaults(data_root: str = None) -> List[str]:
    """Return list of vault names from first-level directories, excluding ignored directories."""
    if data_root is None:
        data_root = str(get_data_root())
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


@logger.trace("workflow_file_discovery")
def discover_workflow_files(vault_path: str) -> List[str]:
    """Return list of workflow file paths in AssistantMD/Workflows (one level deep)."""
    workflows_dir = os.path.join(vault_path, ASSISTANTMD_ROOT_DIR, WORKFLOW_DEFINITIONS_DIR)
    import_dir = os.path.join(vault_path, ASSISTANTMD_ROOT_DIR, IMPORT_DIR)
    context_templates_dir = os.path.join(vault_path, ASSISTANTMD_ROOT_DIR, CONTEXT_TEMPLATE_DIR)

    # Ensure the AssistantMD/Workflows directory exists so new vaults are ready for workflow files
    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(import_dir, exist_ok=True)
    os.makedirs(context_templates_dir, exist_ok=True)

    workflow_files = []

    # Scan for .md files directly in Workflows/
    for item in os.listdir(workflows_dir):
        item_path = os.path.join(workflows_dir, item)

        if item.endswith('.md') and os.path.isfile(item_path):
            workflow_files.append(item_path)
        elif os.path.isdir(item_path) and not item.startswith('_'):
            # Subfolder (not prefixed with underscore) - scan one level deep
            for subitem in os.listdir(item_path):
                if subitem.endswith('.md'):
                    subitem_path = os.path.join(item_path, subitem)
                    if os.path.isfile(subitem_path):
                        workflow_files.append(subitem_path)

    return sorted(workflow_files)


#######################################################################
## Assistant Loading Functions
#######################################################################

@logger.trace("workflow_engine_loading")
def validate_and_load_engine(engine_name: str) -> tuple[types.ModuleType, Callable]:
    """Load and validate a workflow engine module and its run_workflow function.

    Args:
        engine_name: Name of the workflow engine module

    Returns:
        Tuple of (workflow_engine_module, workflow_function)

    Raises:
        ImportError: If workflow engine module cannot be imported
        AttributeError: If run_workflow function is not found in module
    """
    workflow_module = importlib.import_module(f"workflow_engines.{engine_name}.workflow")
    workflow_function = getattr(workflow_module, 'run_workflow')

    if not callable(workflow_function):
        raise AttributeError(f"'run_workflow' in workflow engine '{engine_name}' is not callable")

    return workflow_module, workflow_function

@logger.trace("workflow_loading")
def load_workflow_from_file(
    file_path: str,
    vault: str,
    name: str,
    validated_config: Dict[str, Any],
) -> WorkflowDefinition:
    """Load a WorkflowDefinition from a parsed configuration."""
    # Parse schedule if provided and create actual trigger
    trigger = None
    schedule_string = validated_config['schedule']  # Store original for display
    if schedule_string is not None:
        parsed_schedule = parse_schedule_syntax(schedule_string)
        trigger = create_schedule_trigger(parsed_schedule)

    engine_name = validated_config['workflow_engine']
    workflow_module, workflow_function = validate_and_load_engine(engine_name)

    workflow = WorkflowDefinition(
        vault=vault,
        name=name,
        file_path=file_path,
        trigger=trigger,
        schedule_string=schedule_string,
        workflow_function=workflow_function,
        workflow_module=workflow_module,
        workflow_name=engine_name,
        week_start_day=validated_config['week_start_day'],
        description=validated_config['description'],
        enabled=validated_config['enabled']
    )

    return workflow


#######################################################################
## Assistant Loader Manager
#######################################################################

class WorkflowLoader:
    """
    Manages loading and validation of vault-based workflow configurations with parsed objects.

    WARNING: Direct instantiation is discouraged. Use RuntimeContext.workflow_loader instead
    to ensure proper dependency injection and avoid multiple instances.
    """

    def __init__(self, _data_root: str = None, *, _allow_direct_instantiation: bool = False):
        """
        Initialize the workflow loader.

        Args:
            _data_root: Root directory for vault data
            _allow_direct_instantiation: Internal flag to prevent accidental direct creation

        Raises:
            RuntimeError: If direct instantiation is attempted without permission
        """
        if not _allow_direct_instantiation:
            raise RuntimeError(
                "Direct WorkflowLoader instantiation is discouraged. "
                "Use get_runtime_context().workflow_loader or bootstrap_runtime() instead."
            )
        self._data_root = _data_root or str(get_data_root())
        self._workflows: List[WorkflowDefinition] = []
        self._config_errors: List[ConfigurationError] = []
        self._last_loaded: Optional[datetime] = None
        self._vault_info: Dict[str, Dict[str, Any]] = {}  # Cache vault discovery data

    @logger.trace("workflow_loading")
    async def load_workflows(self, force_reload: bool = False, target_global_id: str = None) -> List[WorkflowDefinition]:
        """Load workflows from all vaults or a specific workflow."""
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
                self._workflows = []
                self._last_loaded = datetime.now()
            return []

        # Clear previous errors on full reload
        if not target_global_id:
            self._config_errors = []

        workflows: List[WorkflowDefinition] = []
        global_ids = set()
        vault_info = {}

        for vault in vaults:
            vault_path = os.path.join(self._data_root, vault)
            workflow_files = discover_workflow_files(vault_path)

            # Cache vault info during processing
            vault_info[vault] = {
                'path': vault_path,
                'workflow_files': workflow_files,
                'workflows': []
            }

            for file_path in workflow_files:
                try:
                    # Extract vault and name from file path
                    path_parts = file_path.replace(self._data_root, '').strip('/').split('/')
                    if len(path_parts) < 4:
                        continue

                    if path_parts[1] != ASSISTANTMD_ROOT_DIR or path_parts[2] != WORKFLOW_DEFINITIONS_DIR:
                        continue

                    vault = path_parts[0]

                    if len(path_parts) == 4:
                        name = os.path.splitext(path_parts[3])[0]
                    elif len(path_parts) == 5:
                        subfolder = path_parts[3]
                        filename = os.path.splitext(path_parts[4])[0]
                        name = f"{subfolder}/{filename}"
                    else:
                        # Unexpected path structure (too deep) - skip
                        continue

                    # Skip if targeting specific workflow and this isn't it
                    if target_name and name != target_name:
                        continue

                    # Parse workflow file using frontmatter format
                    sections = parse_workflow_file(file_path, f"{vault}/{name}")

                    # Extract configuration from frontmatter
                    raw_config = sections.get('__FRONTMATTER_CONFIG__', {})
                    if not raw_config:
                        raise ValueError("Missing YAML frontmatter configuration")

                    # Validate configuration from template/user file
                    validated_config = validate_config(raw_config, vault, name)

                    workflow = load_workflow_from_file(file_path, vault, name, validated_config)

                    # Check for global ID conflicts
                    if workflow.global_id in global_ids:
                        raise ValueError(f"Duplicate workflow global ID: {workflow.global_id}")
                    global_ids.add(workflow.global_id)

                    workflows.append(workflow)

                    # Add to vault cache
                    vault_info[vault]['workflows'].append(workflow.name)

                except Exception as e:
                    # Create configuration error record
                    config_error = ConfigurationError(
                        vault=vault,
                        workflow_name=name if 'name' in locals() else None,
                        file_path=file_path,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        timestamp=datetime.now()
                    )
                    self._config_errors.append(config_error)

                    vault_identifier = f"{vault}/{name}" if 'name' in locals() else vault
                    logger.activity(
                        f"Failed to load workflow file {file_path}: {str(e)}",
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
            if not workflows:
                raise ValueError(f"Target workflow '{target_global_id}' not found")

            target_workflow = workflows[0]

            self._workflows = [workflow for workflow in self._workflows if workflow.global_id != target_global_id]
            self._workflows.append(target_workflow)

            return workflows
        else:
            # Full reload mode - replace entire cache
            self._workflows = workflows
            self._vault_info = vault_info
            self._last_loaded = datetime.now()
            return workflows

    def get_enabled_workflows(self) -> List[WorkflowDefinition]:
        """Get only enabled workflow configurations."""
        return [workflow for workflow in self._workflows if workflow.enabled]

    def get_configuration_errors(self) -> List[ConfigurationError]:
        """Get list of configuration errors encountered during loading."""
        return self._config_errors.copy()

    def get_vault_info(self) -> Dict[str, Dict[str, Any]]:
        """Get cached vault discovery data."""
        return self._vault_info.copy()

    def get_workflow_by_global_id(self, global_id: str) -> Optional[WorkflowDefinition]:
        """Get workflow configuration by global ID (vault/name format)."""
        for workflow in self._workflows:
            if workflow.global_id == global_id:
                return workflow
        return None

    async def ensure_workflow_directories(self, workflow: WorkflowDefinition):
        """Ensure that the workflow's directories exist."""
        workflows_dir = os.path.dirname(workflow.file_path)
        os.makedirs(workflows_dir, exist_ok=True)


# Note: WorkflowLoader instances should be created through RuntimeContext.
# Direct instantiation is discouraged to maintain proper dependency injection.
