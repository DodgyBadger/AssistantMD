
from datetime import datetime
import re
from typing import Dict
from types import SimpleNamespace

from core.logger import UnifiedLogger
from core.core_services import CoreServices
from core.runtime.buffers import BufferStore
from core.utils.routing import OutputTarget, format_input_files_block, write_output
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

    # Get output targets from processed step (optional, may be multiple)
    output_target_value = processed_step.get_directive_value('output')
    if isinstance(output_target_value, list):
        output_targets = output_target_value
    elif output_target_value:
        output_targets = [output_target_value]
    else:
        output_targets = []

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
    if output_targets:
        labels = []
        for output_target in output_targets:
            if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                labels.append(f"variable:{output_target.get('name')}")
            elif isinstance(output_target, dict) and output_target.get("type") == "context":
                labels.append("context")
            elif output_target:
                labels.append(f"file:{output_target}")
        if labels:
            output_target_label = ", ".join(labels)
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
    buffer_store = context.get("buffer_store")
    deps = SimpleNamespace(
        buffer_store=buffer_store,
        buffer_store_registry={"run": buffer_store} if buffer_store is not None else {},
    )
    step_content = await services.generate_response(chat_agent, final_prompt, deps=deps)

    # Write AI-generated content to output targets (if @output specified)
    if output_targets:
        write_mode = processed_step.get_directive_value('write_mode')
        header_value = processed_step.get_directive_value('header')
        wrote_output = False
        for output_target in output_targets:
            if isinstance(output_target, dict) and output_target.get("type") == "context":
                logger.info(
                    "Workflow output target ignored (context not supported)",
                    data={
                        "vault": services.workflow_id,
                        "step_name": step_name,
                    },
                )
                continue
            if isinstance(output_target, dict) and output_target.get("type") == "buffer":
                target = OutputTarget(type="buffer", name=output_target.get("name"))
            else:
                target = OutputTarget(type="file", path=output_target)
            write_result = write_output(
                target=target,
                content=step_content,
                write_mode=write_mode,
                buffer_store=context.get("buffer_store"),
                vault_path=services.vault_path,
                header=header_value,
                buffer_scope=output_target.get("scope") if isinstance(output_target, dict) else None,
                default_scope="run",
                metadata={
                    "source": "workflow_step",
                    "origin_id": services.workflow_id,
                    "origin_name": step_name,
                    "origin_type": "workflow_step",
                    "write_mode": write_mode or "append",
                    "size_chars": len(step_content or ""),
                },
            )
            wrote_output = True
            if write_result.get("type") == "file" and write_result.get("path"):
                context['created_files'].add(write_result.get("path"))
        # Update state manager for any pending patterns used
        context['state_manager'].update_from_processed_step(processed_step)
    else:
        # No output target - step executed for side effects only (e.g., tool calls)
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
