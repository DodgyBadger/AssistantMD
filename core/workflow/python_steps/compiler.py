"""Compile validated python_steps AST blocks into typed step definitions."""

from __future__ import annotations

import ast

from core.workflow.python_steps.models import (
    BranchOp,
    CompiledPythonStepsWorkflow,
    FileInput,
    FileTarget,
    InputSource,
    Operation,
    OutputTarget,
    RunStepOp,
    StepDefinition,
    VarInput,
    VarTarget,
    WriteOp,
)
from core.workflow.python_steps.parser import (
    ParsedPythonStepWorkflow,
    PythonStepsValidationError,
)


def compile_python_steps_workflow(
    workflow: ParsedPythonStepWorkflow,
) -> CompiledPythonStepsWorkflow:
    """Compile parsed python step blocks into typed step definitions."""
    steps: dict[str, StepDefinition] = {}

    for block in workflow.blocks:
        step = _compile_step_block(block.section_name, block.code)
        if step.name in steps:
            raise PythonStepsValidationError(
                f"Duplicate step name '{step.name}'",
                section_name=block.section_name,
                phase="semantic_validation",
            )
        steps[step.name] = step

    _validate_references(steps)
    return CompiledPythonStepsWorkflow(workflow_id=workflow.workflow_id, steps=steps)


def _compile_step_block(section_name: str, code: str) -> StepDefinition:
    module = ast.parse(code, mode="exec")
    step_call = module.body[0].value
    if not isinstance(step_call, ast.Call):
        raise PythonStepsValidationError(
            "Python step blocks must compile from step(...) calls",
            section_name=section_name,
            phase="compile",
        )

    if step_call.args:
        raise PythonStepsValidationError(
            "step(...) does not accept positional arguments",
            section_name=section_name,
            phase="compile",
        )

    kwargs = {kw.arg: kw.value for kw in step_call.keywords if kw.arg is not None}
    name = _required_string(kwargs, "name", section_name=section_name)
    model = _optional_string(kwargs, "model", section_name=section_name)
    prompt = _optional_string(kwargs, "prompt", section_name=section_name)
    inputs = _compile_inputs(kwargs.get("inputs"), section_name=section_name)
    output = _compile_output(kwargs.get("output"), section_name=section_name)
    run = _compile_run(kwargs.get("run"), section_name=section_name)
    extras = _collect_extras(
        kwargs,
        handled={"name", "model", "prompt", "inputs", "output", "run"},
        section_name=section_name,
    )

    if prompt is None and not run:
        raise PythonStepsValidationError(
            "step(...) must define either prompt= or run=",
            section_name=section_name,
            phase="semantic_validation",
        )
    if prompt is not None and run:
        raise PythonStepsValidationError(
            "step(...) cannot define both prompt= and run=",
            section_name=section_name,
            phase="semantic_validation",
        )

    return StepDefinition(
        name=name,
        section_name=section_name,
        model=model,
        prompt=prompt,
        inputs=inputs,
        output=output,
        run=run,
        extras=extras,
    )


def _compile_inputs(node: ast.AST | None, *, section_name: str) -> list[InputSource]:
    if node is None:
        return []
    if not isinstance(node, ast.List):
        raise PythonStepsValidationError(
            "inputs= must be a list",
            section_name=section_name,
            phase="compile",
        )
    return [_compile_input(item, section_name=section_name) for item in node.elts]


def _compile_input(node: ast.AST, *, section_name: str) -> InputSource:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise PythonStepsValidationError(
            "inputs= entries must be SDK calls like files(...) or var(...)",
            section_name=section_name,
            phase="compile",
        )

    func_name = node.func.id
    if func_name in {"file", "files"}:
        path = _first_required_string_arg(node, func_name, section_name=section_name)
        return FileInput(path=path, options=_keyword_literals(node, skip=set()))
    if func_name == "var":
        name = _first_required_string_arg(node, func_name, section_name=section_name)
        return VarInput(name=name, options=_keyword_literals(node, skip=set()))

    raise PythonStepsValidationError(
        f"Unsupported input function '{func_name}'",
        section_name=section_name,
        phase="compile",
    )


def _compile_output(node: ast.AST | None, *, section_name: str) -> OutputTarget | None:
    if node is None:
        return None
    return _compile_target(node, section_name=section_name)


def _compile_target(node: ast.AST, *, section_name: str) -> OutputTarget:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise PythonStepsValidationError(
            "Output targets must be SDK calls like file(...) or var(...)",
            section_name=section_name,
            phase="compile",
        )

    func_name = node.func.id
    if func_name == "file":
        path = _first_required_string_arg(node, func_name, section_name=section_name)
        return FileTarget(path=path, options=_keyword_literals(node, skip=set()))
    if func_name == "var":
        name = _first_required_string_arg(node, func_name, section_name=section_name)
        return VarTarget(name=name, options=_keyword_literals(node, skip=set()))

    raise PythonStepsValidationError(
        f"Unsupported output function '{func_name}'",
        section_name=section_name,
        phase="compile",
    )


def _compile_run(node: ast.AST | None, *, section_name: str) -> list[Operation]:
    if node is None:
        return []
    if not isinstance(node, ast.List):
        raise PythonStepsValidationError(
            "run= must be a list",
            section_name=section_name,
            phase="compile",
        )
    return [_compile_operation(item, section_name=section_name) for item in node.elts]


def _compile_operation(node: ast.AST, *, section_name: str) -> Operation:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise PythonStepsValidationError(
            "run= entries must be SDK operation calls",
            section_name=section_name,
            phase="compile",
        )

    func_name = node.func.id
    if func_name == "run_step":
        return RunStepOp(
            step_name=_first_required_string_arg(node, func_name, section_name=section_name)
        )
    if func_name == "write":
        if len(node.args) != 2 or node.keywords:
            raise PythonStepsValidationError(
                "write(...) requires exactly two positional arguments: target, content",
                section_name=section_name,
                phase="compile",
            )
        target = _compile_target(node.args[0], section_name=section_name)
        content = _literal_string(node.args[1], label="write content", section_name=section_name)
        return WriteOp(target=target, content=content)
    if func_name == "branch":
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        if node.args:
            raise PythonStepsValidationError(
                "branch(...) only supports keyword arguments",
                section_name=section_name,
                phase="compile",
            )
        on_node = kwargs.get("on")
        if_empty_node = kwargs.get("if_empty")
        otherwise_node = kwargs.get("otherwise")
        if on_node is None or if_empty_node is None or otherwise_node is None:
            raise PythonStepsValidationError(
                "branch(...) requires on=, if_empty=, and otherwise=",
                section_name=section_name,
                phase="compile",
            )
        return BranchOp(
            on=_compile_input(on_node, section_name=section_name),
            if_empty=_compile_operation(if_empty_node, section_name=section_name),
            otherwise=_compile_operation(otherwise_node, section_name=section_name),
        )

    raise PythonStepsValidationError(
        f"Unsupported operation '{func_name}'",
        section_name=section_name,
        phase="compile",
    )


def _validate_references(steps: dict[str, StepDefinition]) -> None:
    for step in steps.values():
        for operation in step.run:
            _validate_operation_refs(operation, steps, step_name=step.name)


def _validate_operation_refs(
    operation: Operation,
    steps: dict[str, StepDefinition],
    *,
    step_name: str,
) -> None:
    if isinstance(operation, RunStepOp):
        if operation.step_name not in steps:
            raise PythonStepsValidationError(
                f"Unknown step reference '{operation.step_name}'",
                section_name=step_name,
                phase="semantic_validation",
            )
        return

    if isinstance(operation, BranchOp):
        _validate_operation_refs(operation.if_empty, steps, step_name=step_name)
        _validate_operation_refs(operation.otherwise, steps, step_name=step_name)


def _required_string(
    kwargs: dict[str, ast.AST],
    key: str,
    *,
    section_name: str,
) -> str:
    node = kwargs.get(key)
    if node is None:
        raise PythonStepsValidationError(
            f"step(...) requires {key}=",
            section_name=section_name,
            phase="compile",
        )
    return _literal_string(node, label=key, section_name=section_name)


def _optional_string(
    kwargs: dict[str, ast.AST],
    key: str,
    *,
    section_name: str,
) -> str | None:
    node = kwargs.get(key)
    if node is None:
        return None
    return _literal_string(node, label=key, section_name=section_name)


def _first_required_string_arg(
    call: ast.Call,
    func_name: str,
    *,
    section_name: str,
) -> str:
    if len(call.args) != 1:
        raise PythonStepsValidationError(
            f"{func_name}(...) requires exactly one positional string argument",
            section_name=section_name,
            phase="compile",
        )
    return _literal_string(
        call.args[0],
        label=f"{func_name} argument",
        section_name=section_name,
    )


def _keyword_literals(
    call: ast.Call,
    *,
    skip: set[str],
) -> dict[str, object]:
    compiled: dict[str, object] = {}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in skip:
            continue
        compiled[keyword.arg] = ast.literal_eval(keyword.value)
    return compiled


def _collect_extras(
    kwargs: dict[str, ast.AST],
    *,
    handled: set[str],
    section_name: str,
) -> dict[str, object]:
    extras: dict[str, object] = {}
    for key, value in kwargs.items():
        if key in handled:
            continue
        try:
            extras[key] = ast.literal_eval(value)
        except Exception as exc:  # pragma: no cover - defensive
            raise PythonStepsValidationError(
                f"Unsupported literal value for {key}=",
                section_name=section_name,
                phase="compile",
            ) from exc
    return extras


def _literal_string(node: ast.AST, *, label: str, section_name: str) -> str:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        raise PythonStepsValidationError(
            f"{label} must be a string literal",
            section_name=section_name,
            phase="compile",
        )
    return node.value

