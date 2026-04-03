"""Minimal runtime execution for compiled python_steps workflows."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from core.constants import (
    ASSISTANTMD_ROOT_DIR,
    WORKFLOW_DEFINITIONS_DIR,
    WORKFLOW_SYSTEM_INSTRUCTION,
)
from core.directives.model import ModelDirective
from core.llm.agents import PromptInput, create_agent, generate_response
from core.llm.model_selection import resolve_model_execution_spec
from core.logger import UnifiedLogger
from core.runtime.buffers import BufferStore
from core.utils.routing import OutputTarget, write_output
from core.workflow.parser import parse_workflow_file
from core.workflow.python_steps.models import (
    CompiledPythonStepsWorkflow,
    FileInput,
    InputSource,
    OutputTarget as PythonOutputTarget,
    StepDefinition,
    VarInput,
    VarTarget,
)
from core.workflow.python_steps.parser import validate_python_steps_workflow_definition


logger = UnifiedLogger(tag="python-steps")


@dataclass
class ResolvedInputItem:
    """Single resolved input item."""

    label: str
    content: str


@dataclass
class PythonStepsExecutionContext:
    """Minimal execution context for python_steps workflows."""

    workflow_id: str
    vault_path: str
    workflow_file_path: str
    compiled: CompiledPythonStepsWorkflow
    requested_step_name: str | None = None
    today: datetime = field(default_factory=datetime.today)
    run_buffers: BufferStore = field(default_factory=BufferStore)
    session_buffers: BufferStore = field(default_factory=BufferStore)
    created_files: set[str] = field(default_factory=set)
    completed_steps: set[str] = field(default_factory=set)


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
        context = PythonStepsExecutionContext(
            workflow_id=global_id,
            vault_path=vault_path,
            workflow_file_path=workflow_file_path,
            compiled=compiled,
            requested_step_name=requested_step_name,
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
    final_prompt, prompt_text = _build_step_prompt(step, context=context)
    logger.set_sinks(["validation"]).info(
        "python_step_prompt",
        data={
            "workflow_id": context.workflow_id,
            "step_name": step.name,
            "prompt": prompt_text,
            "output_target": _output_label(step.output),
        },
    )

    model_execution = resolve_model_execution_spec(step.model)
    if model_execution.mode == "skip":
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

    agent = await create_agent(model=model)
    instructions = WORKFLOW_SYSTEM_INSTRUCTION
    if context.compiled.workflow.instructions:
        instructions = f"{instructions}\n\n{context.compiled.workflow.instructions}"
    agent.instructions(lambda _ctx: instructions)

    deps = SimpleNamespace(
        buffer_store=context.run_buffers,
        buffer_store_registry={"run": context.run_buffers, "session": context.session_buffers},
    )
    content = await generate_response(agent, final_prompt, deps=deps)
    if step.output is not None:
        _write_content(
            step.output,
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


def _build_step_prompt(
    step: StepDefinition,
    *,
    context: PythonStepsExecutionContext,
) -> tuple[PromptInput, str]:
    input_chunks: list[str] = []
    for source in step.inputs:
        resolved = _resolve_input_source(source, context=context)
        if not resolved:
            continue
        input_chunks.extend(f"--- INPUT: {item.label} ---\n{item.content}" for item in resolved)

    prompt_parts: list[str] = []
    if input_chunks:
        prompt_parts.append("\n\n".join(input_chunks))
    if step.prompt:
        prompt_parts.append(step.prompt)
    prompt_text = "\n\n".join(part for part in prompt_parts if part.strip())
    return prompt_text, prompt_text


def _resolve_input_source(
    source: InputSource,
    *,
    context: PythonStepsExecutionContext,
) -> list[ResolvedInputItem]:
    if isinstance(source, VarInput):
        store = _buffer_store_for_var(source, context=context)
        entry = store.get(source.name)
        if entry is None or not entry.content:
            return []
        return [ResolvedInputItem(label=f"variable:{source.name}", content=entry.content)]

    return _resolve_file_input(source, context=context)


def _resolve_file_input(
    source: FileInput,
    *,
    context: PythonStepsExecutionContext,
) -> list[ResolvedInputItem]:
    import glob

    pattern = _resolve_runtime_path(source.path, context=context)
    if not os.path.splitext(pattern)[1] and not any(ch in pattern for ch in "*?[]"):
        pattern = f"{pattern}.md"

    full_pattern = os.path.join(context.vault_path, pattern)
    matches = sorted(
        path for path in glob.glob(full_pattern, recursive=True) if os.path.isfile(path)
    )

    resolved: list[ResolvedInputItem] = []
    for path in matches:
        relative = (
            path[len(context.vault_path) + 1 :]
            if path.startswith(f"{context.vault_path}/")
            else path
        )
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        resolved.append(ResolvedInputItem(label=relative, content=content))
    return resolved


def _buffer_store_for_var(
    source: VarInput,
    *,
    context: PythonStepsExecutionContext,
) -> BufferStore:
    scope = str(source.options.get("scope", "run")).strip().lower()
    if scope == "session":
        return context.session_buffers
    return context.run_buffers


def _write_content(
    target: PythonOutputTarget,
    content: str,
    *,
    context: PythonStepsExecutionContext,
    metadata: dict,
) -> None:
    write_mode = _normalize_write_mode(target)
    if isinstance(target, VarTarget):
        write_result = write_output(
            target=OutputTarget(type="buffer", name=target.name),
            content=content,
            write_mode=write_mode,
            buffer_store=context.run_buffers,
            buffer_store_registry={"run": context.run_buffers, "session": context.session_buffers},
            buffer_scope=str(target.options.get("scope", "run")),
            default_scope="run",
            metadata=metadata,
        )
        if write_result.get("type") == "file" and write_result.get("path"):
            context.created_files.add(write_result["path"])
        return

    path = _resolve_runtime_path(target.path, context=context)
    if not os.path.splitext(path)[1]:
        path = f"{path}.md"
    write_result = write_output(
        target=OutputTarget(type="file", path=path),
        content=content,
        write_mode=write_mode,
        buffer_store=context.run_buffers,
        buffer_store_registry={"run": context.run_buffers, "session": context.session_buffers},
        vault_path=context.vault_path,
        metadata=metadata,
    )
    if write_result.get("type") == "file" and write_result.get("path"):
        context.created_files.add(write_result["path"])


def _normalize_write_mode(target: PythonOutputTarget) -> str | None:
    mode = target.options.get("mode")
    if mode is None:
        return "append"
    normalized = str(mode).strip().lower()
    if normalized == "overwrite":
        return "replace"
    return normalized


def _resolve_runtime_path(path: str, *, context: PythonStepsExecutionContext) -> str:
    return path.format(today=context.today.strftime("%Y-%m-%d"))


def _output_label(target: PythonOutputTarget | None) -> str | None:
    if target is None:
        return None
    if isinstance(target, VarTarget):
        return f"variable:{target.name}"
    return f"file:{target.path}"
