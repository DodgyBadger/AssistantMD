
from datetime import datetime
import os
import re
from typing import Dict
from types import SimpleNamespace

from core.logger import UnifiedLogger
from core.core_services import CoreServices
from core.runtime.buffers import BufferStore
from core.utils.routing import format_input_files_block
from core.directives.tools import ToolsDirective

# Create workflow logger
logger = UnifiedLogger(tag="step-workflow")


########################################################################
## Workflow entry. All workflow modules must implement run_workflow.
########################################################################

async def run_workflow(job_args: dict, **kwargs):
    """
    Sequential content generation workflow with predictable, deterministic structure.

    Args:
        job_args: Lightweight job arguments containing:
            - global_id: Workflow identifier (vault/name)
            - config: Configuration dictionary with data_root, etc.
        **kwargs: Additional workflow parameters (e.g., step_name)
    """

    # Create CoreServices fresh from lightweight job arguments
    services = CoreServices(
        job_args['global_id'],
        _data_root=job_args['config']['data_root']
    )

    """
    WORKFLOW PHILOSOPHY:
    - AI as Content Generator: The LLM generates text content for each step
    - Workflow as Controller: Determines where content goes, when steps run, file organization
    - Predictable Structure: Sequential steps (STEP1 → STEP2 → STEP3) with predetermined outputs
    - Linear Processing: Each step builds on previous steps in a defined sequence

    This workflow treats the AI as a content generator that produces text according to prompts,
    while the workflow maintains full control over file operations, step ordering, and output
    destinations. It's designed for structured content creation like planning, journaling,
    reporting, and documentation where predictable organization is important.
    
    CAPABILITIES:
    - Dynamic step discovery (e.g. STEP1, STEP2, STEP3, ...) from workflow file
    - Flexible output files using @output directives with time patterns
    - File content embedding using @input directives  
    - Automatic directory creation for nested paths
    - Configurable week start day for time pattern resolution
    - External tool integration (@tools directive) for enhanced AI capabilities
    
    USE CASES:
    - Daily/weekly planning workflows
    - Structured journaling and reflection
    - Report generation with consistent formatting
    - Documentation creation with predictable organization
    - Content creation where workflow controls structure and AI provides substance
    
    Args:
        services: CoreServices instance providing access to all core functionality
        **kwargs: Optional parameters:
            step_name: If provided, execute only the specified step (ignores @run-on directive)
    """
    
    # Extract parameters from kwargs
    step_name = kwargs.get('step_name')
    
    workflow_steps = []

    try:
        #######################################################################
        ## 1: LOAD AND VALIDATE ASSISTANT CONFIGURATION
        #######################################################################
        
        config = await load_and_validate_config(services, step_name)
        workflow_sections = config['workflow_sections']
        workflow_instructions = config['workflow_instructions']
        workflow_steps = config['workflow_steps']
        
        #######################################################################
        ## 2: INITIALIZE WORKFLOW CONTEXT
        #######################################################################
        
        context = initialize_workflow_context(services)
        
        #######################################################################
        ## 3: PROCESS EACH WORKFLOW STEP
        #######################################################################
        
        for i, current_step in enumerate(workflow_steps):
            raw_step_content = workflow_sections[current_step]
            await process_workflow_step(
                current_step,
                raw_step_content,
                workflow_instructions,
                services,
                i,
                step_name,
                context,
            )
        
        #######################################################################
        ## 4: WORKFLOW COMPLETION
        #######################################################################
        
        # Log successful workflow completion
        created_files = sorted(context['created_files'])
        output_files = []
        for path in created_files:
            if path.startswith(f"{services.vault_path}/"):
                output_files.append(path[len(services.vault_path) + 1:])
            else:
                output_files.append(path)
        max_files = 10
        logger.info(
            "Workflow completed successfully",
            data={
                "vault": services.workflow_id,
                "steps_completed": len(workflow_steps),
                "output_files_created": len(created_files),
                "output_files": output_files[:max_files],
                "output_files_truncated": len(output_files) > max_files,
                "tools_used": sorted(context["tools_used"]),
            },
        )
        
    except Exception as e:
        # Log workflow failure with context
        logger.error(
            "Workflow execution failed",
            data={
                "vault": services.workflow_id,
                "error_message": str(e),
                "steps_attempted": len(workflow_steps),
            },
        )
        raise



########################################################################
## Helper Functions
########################################################################

def generate_numbered_file_path(full_file_path: str, vault_path: str) -> str:
    """Generate a numbered file path for new write mode.
    
    Args:
        full_file_path: Full path to the file (e.g., '/vault/journal/2025-08-19.md')
        vault_path: Root path of the vault
        
    Returns:
        Numbered file path (e.g., '/vault/journal/2025-08-19_0.md')
    """
    # Extract the relative path within the vault
    if full_file_path.startswith(vault_path + '/'):
        relative_path = full_file_path[len(vault_path) + 1:]
    else:
        relative_path = full_file_path
    
    # Remove .md extension to get base path
    if relative_path.endswith('.md'):
        base_path = relative_path[:-3]
    else:
        base_path = relative_path
    
    # Find next available number
    directory = os.path.dirname(base_path) if os.path.dirname(base_path) else '.'
    basename = os.path.basename(base_path)
    
    # Full directory path in vault
    full_directory = os.path.join(vault_path, directory)
    
    existing_numbers = set()
    if os.path.exists(full_directory):
        for filename in os.listdir(full_directory):
            if filename.startswith(f"{basename}_") and filename.endswith('.md'):
                # Extract number from filename (supports both old format _N and new format _NNN)
                number_part = filename[len(basename) + 1:-3]  # Remove prefix_ and .md
                try:
                    number = int(number_part)
                    existing_numbers.add(number)
                except ValueError:
                    # Skip files with non-numeric suffixes
                    continue
    
    # Find the lowest available number starting from 0
    next_number = 0
    while next_number in existing_numbers:
        next_number += 1
    
    # Return full path with zero-padded 3-digit number for proper sorting
    numbered_relative_path = f"{base_path}_{next_number:03d}.md"
    return f"{vault_path}/{numbered_relative_path}"


def generate_numbered_buffer_name(base_name: str, buffer_store) -> str:
    """Generate a numbered variable name for write-mode new."""
    if not base_name:
        base_name = "output"
    existing = set(buffer_store.list().keys()) if buffer_store else set()
    next_number = 0
    candidate = f"{base_name}_{next_number:03d}"
    while candidate in existing:
        next_number += 1
        candidate = f"{base_name}_{next_number:03d}"
    return candidate


def should_step_run_today(processed_step, step_name: str, context: Dict, single_step_name: str, global_id: str) -> bool:
    """Check if step should run today based on @run-on directive."""
    if single_step_name:
        return True

    run_on_days = processed_step.get_directive_value('run_on')
    if not run_on_days:
        # If @run-on is not specified, step runs every day (default behavior)
        return True

    # Check for 'never' option to disable step execution
    if 'never' in run_on_days:
        return False

    # Check for 'daily' option to run every day
    if 'daily' in run_on_days:
        return True

    today = context['today']
    today_name = today.strftime('%A').lower()
    today_abbrev = today.strftime('%a').lower()
    return today_name in run_on_days or today_abbrev in run_on_days


def has_workflow_skip_signal(processed_step) -> tuple[bool, str]:
    """Check if any directive issued a skip signal.

    Directives can signal that a step should be skipped by returning a dict
    with '_workflow_signal': 'skip_step'. This is used by directives like
    @input with required=true when no files are found.

    Returns:
        Tuple of (should_skip, reason)
    """
    input_file_data = processed_step.get_directive_value('input', [])

    # Normalize to list-of-lists format for consistent handling
    if not input_file_data:
        return False, ""
    elif isinstance(input_file_data, list) and input_file_data and isinstance(input_file_data[0], dict):
        # Single @input directive
        input_file_lists = [input_file_data]
    else:
        # Multiple @input directives
        input_file_lists = input_file_data

    # Check each input result for skip signals
    for file_list in input_file_lists:
        for file_data in file_list:
            if isinstance(file_data, dict) and file_data.get('_workflow_signal') == 'skip_step':
                reason = file_data.get('reason', 'Directive signaled skip')
                return True, reason

    return False, ""


def build_final_prompt(processed_step) -> str:
    """Build final prompt with input file content."""
    final_prompt = processed_step.content
    
    input_file_data = processed_step.get_directive_value('input', [])
    if input_file_data:
        formatted = format_input_files_block(input_file_data)
        if formatted:
            final_prompt += "\n\n" + formatted
    
    return final_prompt


def _resolve_tools_result(tools_value) -> tuple[list, str, list]:
    if isinstance(tools_value, list):
        return ToolsDirective.merge_results(
            [value for value in tools_value if isinstance(value, tuple)]
        )
    if isinstance(tools_value, tuple):
        if len(tools_value) >= 3:
            return tools_value[0], tools_value[1], tools_value[2]
        if len(tools_value) == 2:
            return tools_value[0], tools_value[1], []
    return [], "", []




########################################################################
## Helper Functions - Configuration
########################################################################

async def write_step_output(step_content: str, output_file: str, processed_step, 
                            context: Dict, step_index: int, step_name: str, global_id: str):
    """Write step content to output file."""
    try:
        created_files = context['created_files']
        write_mode = processed_step.get_directive_value('write_mode')
        if write_mode == 'new' or write_mode == 'replace':
            file_mode = 'w'
        else:
            file_mode = 'a'
        
        with open(output_file, file_mode, encoding='utf-8') as file:
            # Check for custom header from @header directive
            custom_header = processed_step.get_directive_value('header')
            if custom_header:
                file.write(f"# {custom_header}\n\n")
            file.write(step_content)
            file.write("\n\n")
        
        created_files.add(output_file)
        context['state_manager'].update_from_processed_step(processed_step)
            
    except (IOError, OSError, PermissionError) as file_error:
        logger.error(
            "Failed to create output file",
            data={
                "vault": global_id,
                "target_file": output_file,
                "step_name": step_name,
                "reason": str(file_error),
            },
        )
        raise


def write_step_output_to_buffer(
    step_content: str,
    variable_name: str,
    processed_step,
    context: Dict,
) -> None:
    """Write step content to a buffer variable."""
    buffer_store = context.get("buffer_store")
    if buffer_store is None:
        raise ValueError("Buffer store unavailable for variable output")
    write_mode = processed_step.get_directive_value('write_mode')
    if write_mode == "replace":
        buffer_mode = "replace"
    else:
        buffer_mode = "append"
    buffer_store.put(
        variable_name,
        step_content,
        mode=buffer_mode,
        metadata={
            "source": "workflow_step",
            "step": processed_step,
        },
    )

async def create_step_agent(processed_step, workflow_instructions: str, services: CoreServices):
    """Create AI agent for step execution with optional tool integration."""
    # Get model instance from model directive (None if not specified)
    model_instance = processed_step.get_directive_value('model', None)

    # Get tools and enhanced instructions from tools directive
    tools_result = processed_step.get_directive_value('tools', [])
    tool_functions, tool_instructions, _ = _resolve_tools_result(tools_result)

    # Compose instructions using Pydantic AI's list support for clean composition
    if tool_instructions:
        instructions_stack = [workflow_instructions, tool_instructions]
    else:
        instructions_stack = [workflow_instructions]

    agent = await services.create_agent(model_instance, tool_functions)
    for inst in instructions_stack:
        if inst:
            agent.instructions(lambda _ctx, text=inst: text)
    return agent


def initialize_workflow_context(services: CoreServices):
    """Initialize workflow execution context."""
    today = datetime.today()
    day_name = today.strftime('%A')
    today_formatted = today.strftime('%Y-%m-%d')
    
    return {
        'today': today,
        'day_name': day_name,
        'today_formatted': today_formatted,
        'week_start_day': services.week_start_day,
        'state_manager': services.get_state_manager(),
        'created_files': set(),
        'tools_used': set(),
        'buffer_store': BufferStore(),
    }


async def process_workflow_step(
    step_name: str,
    raw_step_content: str,
    workflow_instructions: str,
    services: CoreServices,
    step_index: int,
    single_step_name: str,
    context: Dict,
):
    """Process a single workflow step with all directives and AI generation."""
    today = context['today']

    # Process all directives with current context (single parse operation)
    processed_step = services.process_step(
        raw_step_content,
        reference_date=today,
        buffer_store=context.get("buffer_store"),
    )

    # Get output file path from processed step (optional)
    output_target = processed_step.get_directive_value('output')
    output_file = None
    output_variable = None

    if output_target:
        # Apply write-mode from processed step (no re-parsing)
        write_mode = processed_step.get_directive_value('write_mode')
        if isinstance(output_target, dict) and output_target.get("type") == "buffer":
            output_variable = output_target.get("name")
            if write_mode == "new":
                output_variable = generate_numbered_buffer_name(
                    output_variable or "output",
                    context.get("buffer_store"),
                )
        else:
            output_file_path = output_target
            output_file = f'{services.vault_path}/{output_file_path}'
            if write_mode == 'new':
                output_file = generate_numbered_file_path(output_file, services.vault_path)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Check @run-on directive for scheduled execution
    if not should_step_run_today(processed_step, step_name, context, single_step_name, services.workflow_id):
        logger.set_sinks(["validation"]).info(
            "workflow_step_skipped",
            data={
                "step_name": step_name,
                "reason": "run_on",
            },
        )
        return  # Skip this step

    # Check for workflow skip signals from directives (e.g., required input files missing)
    should_skip, skip_reason = has_workflow_skip_signal(processed_step)
    if should_skip:
        logger.add_sink("validation").info(
            f"Step skipped: {skip_reason}",
            data={
                "event": "workflow_step_skipped",
                "vault": services.workflow_id,
                "step_name": step_name,
                "reason": skip_reason,
            },
        )
        return  # Skip this step

    tools_result = processed_step.get_directive_value('tools', [])
    tool_functions, _, tool_specs = _resolve_tools_result(tools_result)
    if tool_functions:
        if tool_specs:
            tool_names = [spec.name for spec in tool_specs]
        else:
            raw_tools = None
            for line in raw_step_content.splitlines():
                stripped = line.strip()
                if stripped.startswith("@tools"):
                    raw_tools = stripped[len("@tools"):].strip()
                    break
            if raw_tools:
                tool_names = [name for name in re.split(r"[ ,]+", raw_tools) if name]
            else:
                tool_names = [
                    getattr(tool, "__name__", "tool") for tool in tool_functions
                ]
        context["tools_used"].update(tool_names)

    # Build final prompt with input file content
    final_prompt = build_final_prompt(processed_step)
    output_target_label = None
    if output_variable is not None:
        output_target_label = f"variable:{output_variable}"
    elif isinstance(output_target, dict) and output_target.get("type") == "buffer":
        output_target_label = f"variable:{output_target.get('name')}"
    elif output_target:
        output_target_label = f"file:{output_target}"
    logger.set_sinks(["validation"]).info(
        "workflow_step_prompt",
        data={
            "step_name": step_name,
            "output_target": output_target_label,
            "prompt": final_prompt,
        },
    )

    # Generate AI content
    chat_agent = await create_step_agent(processed_step, workflow_instructions, services)
    deps = SimpleNamespace(buffer_store=context.get("buffer_store"))
    step_content = await services.generate_response(chat_agent, final_prompt, deps=deps)

    # Write AI-generated content to output file (if @output specified)
    if output_file:
        await write_step_output(step_content, output_file, processed_step,
                                context, step_index, step_name, services.workflow_id)
    elif output_variable:
        write_step_output_to_buffer(step_content, output_variable, processed_step, context)
    else:
        # No output file - step executed for side effects only (e.g., tool calls)
        # Still update state manager for any pending patterns used
        context['state_manager'].update_from_processed_step(processed_step)


async def load_and_validate_config(services: CoreServices, step_name: str = None):
    """Load workflow file and validate configuration."""
    workflow_sections = services.get_workflow_sections()
    
    # Extract any section containing "instructions" (case-insensitive), then filter them out from steps.
    instruction_keys = [
        section_name for section_name in workflow_sections.keys()
        if "instructions" in section_name.strip().lower()
    ]
    workflow_instructions = "\n\n".join(
        [
            workflow_sections.get(section_name, "").strip()
            for section_name in instruction_keys
            if workflow_sections.get(section_name, "").strip()
        ]
    )
    if not workflow_instructions or not workflow_instructions.strip():
        workflow_instructions = "You are a helpful assistant."

    # Filter instruction sections from workflow steps (they are not executable steps)
    if instruction_keys:
        workflow_steps = [k for k in workflow_sections.keys() if k not in instruction_keys]
    else:
        workflow_steps = list(workflow_sections.keys())
    
    if not workflow_steps:
        error_msg = "No workflow sections found after the instructions block. Please add at least one section."
        raise ValueError(error_msg)
    
    if step_name:
        if step_name not in workflow_steps:
            error_msg = f"Step '{step_name}' not found. Available steps: {', '.join(workflow_steps)}"
            raise ValueError(error_msg)
        workflow_steps = [step_name]
    
    return {
        'workflow_sections': workflow_sections,
        'workflow_instructions': workflow_instructions,
        'workflow_steps': workflow_steps
    }
