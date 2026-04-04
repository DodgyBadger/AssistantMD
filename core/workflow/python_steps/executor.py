"""Runtime execution for compiled python_steps workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from core.chunking.prompt_builder import PromptInput, build_input_files_prompt
from core.constants import (
    ASSISTANTMD_ROOT_DIR,
    VALID_WEEK_DAYS,
    WORKFLOW_DEFINITIONS_DIR,
)
from core.directives.model import ModelDirective
from core.llm.agents import create_agent, generate_response
from core.logger import UnifiedLogger
from core.runtime.buffers import BufferStore
from core.utils.file_state import WorkflowFileStateManager
from core.workflow.parser import parse_workflow_file
from core.workflow.input_resolution import build_input_request, resolve_input_request
from core.workflow.execution_prep import (
    build_step_prompt,
    compose_instruction_layers,
    resolve_step_model_execution,
    should_step_run_today,
)
from core.workflow.output_resolution import (
    build_output_request,
    normalize_write_mode,
    resolve_header_value,
    resolve_output_request,
    write_resolved_output,
)
from core.workflow.tool_binding import ToolBindingResult, resolve_tool_binding
from core.workflow.python_steps.models import (
    CompiledPythonStepsWorkflow,
    InputSource,
    OutputTarget as PythonOutputTarget,
    FileTarget,
    StepDefinition,
    VarInput,
    VarTarget,
)
from core.workflow.python_steps.parser import validate_python_steps_workflow_definition


logger = UnifiedLogger(tag="python-steps")


def _current_datetime_today() -> datetime:
    """Resolve today's date at runtime so validation can monkey-patch the module clock."""
    return datetime.today()


@dataclass
class ResolvedInputItem:
    """Resolved input payload for one source."""

    records: list[dict[str, object]]


@dataclass
class PythonStepsExecutionContext:
    """Minimal execution context for python_steps workflows."""

    workflow_id: str
    vault_path: str
    workflow_file_path: str
    compiled: CompiledPythonStepsWorkflow
    requested_step_name: str | None = None
    today: datetime = field(default_factory=_current_datetime_today)
    week_start_day: int = 0
    run_buffers: BufferStore = field(default_factory=BufferStore)
    session_buffers: BufferStore = field(default_factory=BufferStore)
    state_manager: WorkflowFileStateManager | None = None
    created_files: set[str] = field(default_factory=set)
    completed_steps: set[str] = field(default_factory=set)
    tools_used: set[str] = field(default_factory=set)


class PythonStepsExecutionError(ValueError):
    """Execution error with step-facing context for workflow debugging."""

    def __init__(self, message: str, *, step_name: str | None, phase: str) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.phase = phase


async def run_python_steps_workflow(job_args: dict, **kwargs) -> None:
    """Execute the minimal runnable python_steps subset."""
    global_id = job_args["global_id"]
    data_root = job_args["config"]["data_root"]
    requested_step_name = kwargs.get("step_name")
    expected_failure = bool(kwargs.get("expected_failure", False))

    workflow_name = global_id.split("/", 1)[1]
    vault_path = os.path.join(data_root, global_id.split("/", 1)[0])
    workflow_file_path = os.path.join(
        vault_path,
        ASSISTANTMD_ROOT_DIR,
        WORKFLOW_DEFINITIONS_DIR,
        f"{workflow_name}.md",
    )

    try:
        sections = parse_workflow_file(workflow_file_path, global_id)
        compiled = validate_python_steps_workflow_definition(
            workflow_id=global_id,
            file_path=workflow_file_path,
            sections=sections,
            validated_config=sections.get("__FRONTMATTER_CONFIG__", {}),
        )
        workflow_config = sections.get("__FRONTMATTER_CONFIG__", {}) or {}
        week_start_day_name = str(workflow_config.get("week_start_day", "monday")).strip().lower()
        week_start_day = VALID_WEEK_DAYS.index(week_start_day_name)
        context = PythonStepsExecutionContext(
            workflow_id=global_id,
            vault_path=vault_path,
            workflow_file_path=workflow_file_path,
            compiled=compiled,
            requested_step_name=requested_step_name,
            week_start_day=week_start_day,
            state_manager=WorkflowFileStateManager(global_id.split("/", 1)[0], global_id),
        )

        if requested_step_name:
            step = compiled.steps.get(requested_step_name)
            if step is None:
                raise PythonStepsExecutionError(
                    (
                        f"Step '{requested_step_name}' not found. Available steps: "
                        f"{', '.join(compiled.workflow.step_names)}"
                    ),
                    step_name=requested_step_name,
                    phase="entry_selection",
                )
            await _execute_step(step, context)
        else:
            logger.set_sinks(["validation"]).info(
                "python_workflow_started",
                data={
                    "workflow_id": context.workflow_id,
                    "step_names": compiled.workflow.step_names,
                },
            )
            for step_name in compiled.workflow.step_names:
                await _execute_step(compiled.steps[step_name], context)
            logger.set_sinks(["validation"]).info(
                "python_workflow_completed",
                data={
                    "workflow_id": context.workflow_id,
                    "step_count": len(compiled.workflow.step_names),
                    "tools_used": sorted(context.tools_used),
                },
            )

        created_files = sorted(context.created_files)
        output_files = [
            path[len(context.vault_path) + 1 :]
            if path.startswith(f"{context.vault_path}/")
            else path
            for path in created_files
        ]
        logger.info(
            "Workflow completed successfully",
            data={
                "vault": global_id,
                "steps_completed": len(context.completed_steps),
                "output_files_created": len(created_files),
                "output_files": output_files[:10],
                "output_files_truncated": len(output_files) > 10,
            },
        )
    except Exception as exc:
        failure = {
            "vault": global_id,
            "error_message": str(exc),
            "steps_attempted": 0,
            "template_pointer": f"## {getattr(exc, 'step_name', '')}".strip(),
            "step_name": getattr(exc, "step_name", None),
            "phase": getattr(exc, "phase", None),
        }
        if expected_failure:
            logger.info("Workflow execution failed (expected)", data=failure)
        else:
            logger.error("Workflow execution failed", data=failure)
        raise


async def _execute_step(
    step: StepDefinition,
    context: PythonStepsExecutionContext,
) -> None:
    if step.name in context.completed_steps:
        return

    logger.set_sinks(["validation"]).info(
        "python_step_started",
        data={
            "workflow_id": context.workflow_id,
            "step_name": step.name,
            "step_type": "prompt",
        },
    )

    await _execute_prompt_step(step, context)

    context.completed_steps.add(step.name)
    logger.set_sinks(["validation"]).info(
        "python_step_completed",
        data={
            "workflow_id": context.workflow_id,
            "step_name": step.name,
        },
    )


async def _execute_prompt_step(
    step: StepDefinition,
    context: PythonStepsExecutionContext,
) -> None:
    if not should_step_run_today(
        step.extras.get("run_on"),
        today=context.today,
        single_step_name=context.requested_step_name,
    ):
        logger.set_sinks(["validation"]).info(
            "python_step_skipped",
            data={
                "workflow_id": context.workflow_id,
                "step_name": step.name,
                "reason": "run_on",
            },
        )
        return

    model_execution = resolve_step_model_execution(step.model)
    resolved_inputs, skip_reason = _resolve_step_inputs(step, context=context)
    tool_binding = _resolve_step_tools(step, context=context)
    if tool_binding.tool_specs:
        tool_names = tool_binding.tool_names()
        context.tools_used.update(tool_names)
        logger.set_sinks(["validation"]).info(
            "python_step_tools",
            data={
                "workflow_id": context.workflow_id,
                "step_name": step.name,
                "tool_names": tool_names,
            },
        )
    if skip_reason:
        logger.set_sinks(["validation"]).info(
            "python_step_skipped",
            data={
                "workflow_id": context.workflow_id,
                "step_name": step.name,
                "reason": skip_reason,
            },
        )
        return

    final_prompt, prompt_text, attached_image_count, prompt_warnings = build_step_prompt(
        base_prompt=step.prompt or "",
        input_file_data=[item.records for item in resolved_inputs if item.records],
        vault_path=context.vault_path,
        model_execution=model_execution,
    )
    logger.set_sinks(["validation"]).info(
        "python_step_prompt",
        data={
            "workflow_id": context.workflow_id,
            "step_name": step.name,
            "prompt": prompt_text,
            "output_target": _output_labels(_step_outputs(step)),
            "attached_image_count": attached_image_count,
            "prompt_warnings": prompt_warnings,
        },
    )

    if model_execution.mode == "skip":
        _mark_processed_inputs(resolved_inputs, context=context)
        logger.set_sinks(["validation"]).info(
            "python_step_skipped",
            data={
                "workflow_id": context.workflow_id,
                "step_name": step.name,
                "reason": "model_none",
            },
        )
        return

    model = None
    if step.model:
        model = ModelDirective().process_value(step.model, context.vault_path)

    agent = await create_agent(model=model, tools=tool_binding.tool_functions)
    for inst in compose_instruction_layers(
        workflow_instructions=context.compiled.workflow.instructions,
        tool_instructions=tool_binding.tool_instructions,
    ):
        agent.instructions(lambda _ctx, text=inst: text)

    deps = SimpleNamespace(
        buffer_store=context.run_buffers,
        buffer_store_registry={"run": context.run_buffers, "session": context.session_buffers},
    )
    content = await generate_response(agent, final_prompt, deps=deps)
    for output_target in _step_outputs(step):
        _write_content(
            output_target,
            content,
            context=context,
            metadata={
                "source": "python_step",
                "origin_id": context.workflow_id,
                "origin_name": step.name,
                "origin_type": "python_step",
                "size_chars": len(content or ""),
            },
        )
    _mark_processed_inputs(resolved_inputs, context=context)


def _resolve_step_inputs(
    step: StepDefinition,
    *,
    context: PythonStepsExecutionContext,
) -> tuple[list[ResolvedInputItem], str | None]:
    resolved_items: list[ResolvedInputItem] = []
    for source in step.inputs:
        resolved = _resolve_input_source(source, context=context)
        if _is_skip_signal(resolved):
            reason = str(resolved[0].get("reason") or "Directive signaled skip")
            return [], reason
        if resolved:
            resolved_items.append(ResolvedInputItem(records=resolved))
    return resolved_items, None


def _resolve_input_source(
    source: InputSource,
    *,
    context: PythonStepsExecutionContext,
) -> list[dict[str, object]]:
    request = _source_to_input_request(source, context=context)
    return resolve_input_request(
        request,
        vault_path=context.vault_path,
        reference_date=context.today,
        week_start_day=context.week_start_day,
        state_manager=context.state_manager,
        buffer_store=context.run_buffers,
        buffer_store_registry={
            "run": context.run_buffers,
            "session": context.session_buffers,
        },
    )


def _source_to_input_request(
    source: InputSource,
    *,
    context: PythonStepsExecutionContext,
) -> object:
    if isinstance(source, VarInput):
        target_type = "variable"
        target = source.name
    else:
        target_type = "file"
        target = source.path
    return build_input_request(target_type=target_type, target=target, parameters=dict(source.options))


def _is_skip_signal(records: list[dict[str, object]]) -> bool:
    if not records:
        return False
    first = records[0]
    return isinstance(first, dict) and first.get("_workflow_signal") == "skip_step"


def _mark_processed_inputs(
    resolved_inputs: list[ResolvedInputItem],
    *,
    context: PythonStepsExecutionContext,
) -> None:
    if context.state_manager is None:
        return
    for item in resolved_inputs:
        for record in item.records:
            state_metadata = record.get("_state_metadata")
            if not isinstance(state_metadata, dict):
                continue
            if not state_metadata.get("requires_tracking"):
                continue
            pattern = state_metadata.get("pattern")
            file_records = state_metadata.get("file_records")
            if isinstance(pattern, str) and isinstance(file_records, list):
                context.state_manager.mark_files_processed(file_records, pattern)


def _write_content(
    target: PythonOutputTarget,
    content: str,
    *,
    context: PythonStepsExecutionContext,
    metadata: dict,
) -> None:
    write_mode = _normalize_write_mode(target)
    resolved_target = _resolve_output_target(target, context=context)
    write_result = write_resolved_output(
        resolved_target=resolved_target,
        content=content,
        write_mode=write_mode,
        vault_path=context.vault_path,
        buffer_store=context.run_buffers,
        buffer_store_registry={"run": context.run_buffers, "session": context.session_buffers},
        header=_resolve_output_header(target, context=context),
        metadata=metadata,
        default_scope="run",
    )
    if write_result.get("type") == "file" and write_result.get("path"):
        context.created_files.add(write_result["path"])


def _normalize_write_mode(target: PythonOutputTarget) -> str | None:
    mode = target.options.get("mode")
    if mode is None:
        return "append"
    normalized = str(mode).strip().lower()
    if normalized == "overwrite":
        normalized = "replace"
    return normalize_write_mode(normalized)


def _resolve_output_target(target: PythonOutputTarget, *, context: PythonStepsExecutionContext):
    if isinstance(target, VarTarget):
        return resolve_output_request(
            build_output_request(
                target_type="variable",
                target=target.name,
                parameters=_output_target_parameters(target),
            ),
            vault_path=context.vault_path,
        )

    if not isinstance(target, FileTarget):
        raise PythonStepsExecutionError(
            f"Unsupported output target type: {type(target).__name__}",
            step_name=None,
            phase="output_target",
        )

    return resolve_output_request(
        build_output_request(
            target_type="file",
            target=target.path,
            parameters=_output_target_parameters(target),
        ),
        vault_path=context.vault_path,
        reference_date=context.today,
        week_start_day=context.week_start_day,
    )


def _output_target_parameters(target: PythonOutputTarget) -> dict[str, object]:
    if isinstance(target, VarTarget) and "scope" in target.options:
        return {"scope": target.options["scope"]}
    return {}


def _resolve_output_header(
    target: PythonOutputTarget,
    *,
    context: PythonStepsExecutionContext,
) -> str | None:
    if not isinstance(target, FileTarget):
        return None
    raw_header = target.options.get("header")
    if raw_header is None:
        return None
    text = str(raw_header).strip()
    if not text:
        return None
    return resolve_header_value(
        text,
        reference_date=context.today,
        week_start_day=context.week_start_day,
    )


def _resolve_step_tools(
    step: StepDefinition,
    *,
    context: PythonStepsExecutionContext,
) -> ToolBindingResult:
    tools_value = step.extras.get("tools")
    if tools_value is None:
        return ToolBindingResult(tool_functions=[], tool_instructions="", tool_specs=[])
    return resolve_tool_binding(
        tools_value,
        vault_path=context.vault_path,
        week_start_day=context.week_start_day,
    )


def _step_outputs(step: StepDefinition) -> list[PythonOutputTarget]:
    if step.outputs:
        return list(step.outputs)
    if step.output is not None:
        return [step.output]
    return []
def _output_label(target: PythonOutputTarget | None) -> str | None:
    if target is None:
        return None
    if isinstance(target, VarTarget):
        return f"variable:{target.name}"
    return f"file:{target.path}"


def _output_labels(targets: list[PythonOutputTarget]) -> str | None:
    if not targets:
        return None
    labels = [label for label in (_output_label(target) for target in targets) if label]
    if not labels:
        return None
    return ", ".join(labels)
