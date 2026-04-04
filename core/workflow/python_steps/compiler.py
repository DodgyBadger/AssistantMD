"""Compile validated python_steps AST blocks into typed workflow definitions."""

from __future__ import annotations

import ast

from core.authoring import AUTHORING_TARGET_METHODS
from core.authoring.primitives import DateValue, PathValue
from core.workflow.python_steps.models import (
    CompiledPythonStepsWorkflow,
    FileInput,
    FileTarget,
    InputSource,
    OutputTarget,
    OutputTargets,
    StepDefinition,
    VarInput,
    VarTarget,
    WorkflowDefinition,
)
from core.workflow.python_steps.parser import (
    ParsedPythonStepWorkflow,
    PythonStepsValidationError,
)


def compile_python_steps_workflow(
    workflow: ParsedPythonStepWorkflow,
) -> CompiledPythonStepsWorkflow:
    """Compile parsed python workflow block into typed definitions."""
    module = ast.parse(workflow.code, mode="exec")
    context = _CompilationContext(block_label=workflow.block_label)

    for statement in module.body[:-1]:
        _compile_assignment(statement, context=context)

    if context.workflow is None:
        raise PythonStepsValidationError(
            "Workflow(...) declaration is required before workflow.run()",
            section_name=context.block_label,
            phase="semantic_validation",
        )

    run_call = module.body[-1].value
    if not isinstance(run_call, ast.Call):
        raise PythonStepsValidationError(
            "workflow.run() must be the terminal expression",
            section_name=context.block_label,
            phase="compile",
        )

    workflow_name = _workflow_name_from_run_call(run_call, section_name=context.block_label)
    if workflow_name != context.workflow.declaration_name:
        raise PythonStepsValidationError(
            "workflow.run() must target the declared Workflow(...) object",
            section_name=context.workflow.declaration_name,
            phase="semantic_validation",
        )

    ordered_steps = {name: context.steps[name] for name in context.workflow.step_names}
    return CompiledPythonStepsWorkflow(
        workflow_id=workflow.workflow_id,
        workflow=context.workflow,
        steps=ordered_steps,
    )


class _CompilationContext:
    """Holds compilation state for a single workflow block."""

    def __init__(self, *, block_label: str | None) -> None:
        self.block_label = block_label
        self.constants: dict[str, object] = {}
        self.steps_by_declaration: dict[str, StepDefinition] = {}
        self.steps: dict[str, StepDefinition] = {}
        self.workflow: WorkflowDefinition | None = None


def _compile_assignment(statement: ast.stmt, *, context: _CompilationContext) -> None:
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        raise PythonStepsValidationError(
            "Top-level statements must be simple assignments",
            section_name=context.block_label,
            phase="compile",
        )

    target = statement.targets[0]
    if not isinstance(target, ast.Name):
        raise PythonStepsValidationError(
            "Top-level assignments must target a simple name",
            section_name=context.block_label,
            phase="compile",
        )

    value = statement.value
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id == "Step":
            step = _compile_step(target.id, value, context=context)
            if target.id in context.steps_by_declaration:
                raise PythonStepsValidationError(
                    f"Duplicate step declaration '{target.id}'",
                    section_name=target.id,
                    phase="semantic_validation",
                )
            if step.name in context.steps:
                raise PythonStepsValidationError(
                    f"Duplicate step name '{step.name}'",
                    section_name=target.id,
                    phase="semantic_validation",
                )
            context.steps_by_declaration[target.id] = step
            context.steps[step.name] = step
            return
        if value.func.id == "Workflow":
            if context.workflow is not None:
                raise PythonStepsValidationError(
                    "Only one Workflow(...) declaration is allowed",
                    section_name=target.id,
                    phase="semantic_validation",
                )
            context.workflow = _compile_workflow(target.id, value, context=context)
            return
    if _is_sdk_constant_expr(value):
        if target.id in context.constants:
            raise PythonStepsValidationError(
                f"Duplicate constant '{target.id}'",
                section_name=target.id,
                phase="semantic_validation",
            )
        context.constants[target.id] = _compile_sdk_constant(
            value,
            context=context,
            section_name=target.id,
        )
        return

    if target.id in context.constants:
        raise PythonStepsValidationError(
            f"Duplicate constant '{target.id}'",
            section_name=target.id,
            phase="semantic_validation",
        )
    context.constants[target.id] = _resolve_literal(statement.value, context=context)


def _compile_step(
    declaration_name: str,
    call: ast.Call,
    *,
    context: _CompilationContext,
) -> StepDefinition:
    if call.args:
        raise PythonStepsValidationError(
            "Step(...) does not accept positional arguments",
            section_name=declaration_name,
            phase="compile",
        )

    kwargs = _keyword_map(call, section_name=declaration_name)
    name = _required_string(kwargs, "name", context=context, section_name=declaration_name)
    model = _optional_string(kwargs, "model", context=context, section_name=declaration_name)
    prompt = _required_string(kwargs, "prompt", context=context, section_name=declaration_name)
    inputs = _compile_inputs(kwargs.get("inputs"), context=context, section_name=declaration_name)
    output = _compile_output(kwargs.get("output"), context=context, section_name=declaration_name)
    outputs = _compile_outputs(kwargs.get("outputs"), context=context, section_name=declaration_name)
    if output is not None and outputs:
        raise PythonStepsValidationError(
            "Step(...) cannot declare both output= and outputs=",
            section_name=declaration_name,
            phase="compile",
        )
    extras = _collect_extras(
        kwargs,
        handled={"name", "model", "prompt", "inputs", "output", "outputs"},
        context=context,
    )
    return StepDefinition(
        declaration_name=declaration_name,
        name=name,
        model=model,
        prompt=prompt,
        inputs=inputs,
        output=output,
        outputs=outputs,
        extras=extras,
    )


def _compile_workflow(
    declaration_name: str,
    call: ast.Call,
    *,
    context: _CompilationContext,
) -> WorkflowDefinition:
    if call.args:
        raise PythonStepsValidationError(
            "Workflow(...) does not accept positional arguments",
            section_name=declaration_name,
            phase="compile",
        )

    kwargs = _keyword_map(call, section_name=declaration_name)
    instructions = _optional_string(
        kwargs,
        "instructions",
        context=context,
        section_name=declaration_name,
    )
    step_names, step_declarations = _compile_workflow_steps(
        kwargs.get("steps"),
        context=context,
        section_name=declaration_name,
    )
    extras = set(kwargs) - {"instructions", "steps"}
    if extras:
        raise PythonStepsValidationError(
            f"Unsupported Workflow(...) arguments: {', '.join(sorted(extras))}",
            section_name=declaration_name,
            phase="compile",
        )
    return WorkflowDefinition(
        declaration_name=declaration_name,
        instructions=instructions,
        step_names=step_names,
        step_declarations=step_declarations,
    )


def _compile_workflow_steps(
    node: ast.AST | None,
    *,
    context: _CompilationContext,
    section_name: str,
) -> tuple[list[str], list[str]]:
    if node is None:
        raise PythonStepsValidationError(
            "Workflow(...) requires steps=[...]",
            section_name=section_name,
            phase="compile",
        )
    if not isinstance(node, ast.List):
        raise PythonStepsValidationError(
            "Workflow steps must be declared as a list",
            section_name=section_name,
            phase="compile",
        )

    step_names: list[str] = []
    step_declarations: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Name):
            raise PythonStepsValidationError(
                "Workflow steps must reference declared Step(...) names",
                section_name=section_name,
                phase="compile",
            )
        declaration_name = item.id
        step_declarations.append(declaration_name)
        step = context.steps_by_declaration.get(declaration_name)
        if step is None:
            raise PythonStepsValidationError(
                f"Unknown step reference '{declaration_name}'",
                section_name=section_name,
                phase="semantic_validation",
            )
        step_names.append(step.name)
    if not step_names:
        raise PythonStepsValidationError(
            "Workflow(...) must declare at least one step",
            section_name=section_name,
            phase="semantic_validation",
        )
    return step_names, step_declarations


def _compile_inputs(
    node: ast.AST | None,
    *,
    context: _CompilationContext,
    section_name: str,
) -> list[InputSource]:
    if node is None:
        return []
    if not isinstance(node, ast.List):
        raise PythonStepsValidationError(
            "inputs= must be a list",
            section_name=section_name,
            phase="compile",
        )
    return [
        _compile_input(item, context=context, section_name=section_name)
        for item in node.elts
    ]


def _compile_input(
    node: ast.AST,
    *,
    context: _CompilationContext,
    section_name: str,
) -> InputSource:
    if isinstance(node, ast.Name):
        constant = _resolve_literal(node, context=context)
        if isinstance(constant, FileTarget):
            return FileInput(path=constant.path, options=dict(constant.options))
        if isinstance(constant, VarTarget):
            return VarInput(name=constant.name, options=dict(constant.options))
        raise PythonStepsValidationError(
            "inputs= constants must resolve to File(...) or Var(...)",
            section_name=section_name,
            phase="compile",
        )

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise PythonStepsValidationError(
            "inputs= entries must be File(...) or Var(...) calls",
            section_name=section_name,
            phase="compile",
        )

    func_name = node.func.id
    if func_name == "File":
        path = _first_required_path_arg(
            node,
            func_name,
            context=context,
            section_name=section_name,
        )
        return FileInput(path=path, options=_keyword_literals(node, context=context))
    if func_name == "Var":
        name = _first_required_string_arg(
            node,
            func_name,
            context=context,
            section_name=section_name,
        )
        return VarInput(name=name, options=_keyword_literals(node, context=context))

    raise PythonStepsValidationError(
        f"Unsupported input function '{func_name}'",
        section_name=section_name,
        phase="compile",
    )


def _compile_output(
    node: ast.AST | None,
    *,
    context: _CompilationContext,
    section_name: str,
) -> OutputTarget | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        constant = _resolve_literal(node, context=context)
        if isinstance(constant, FileTarget | VarTarget):
            return constant
        raise PythonStepsValidationError(
            "output= constants must resolve to File(...) or Var(...)",
            section_name=section_name,
            phase="compile",
        )
    return _compile_target(node, context=context, section_name=section_name)


def _compile_outputs(
    node: ast.AST | None,
    *,
    context: _CompilationContext,
    section_name: str,
) -> OutputTargets:
    if node is None:
        return []
    if isinstance(node, ast.Name):
        constant = _resolve_literal(node, context=context)
        if isinstance(constant, list) and all(isinstance(item, FileTarget | VarTarget) for item in constant):
            return list(constant)
        raise PythonStepsValidationError(
            "outputs= constants must resolve to a list of File(...) or Var(...) targets",
            section_name=section_name,
            phase="compile",
        )
    if not isinstance(node, ast.List):
        raise PythonStepsValidationError(
            "outputs= must be a list",
            section_name=section_name,
            phase="compile",
        )
    return [_compile_target(item, context=context, section_name=section_name) for item in node.elts]


def _compile_target(
    node: ast.AST,
    *,
    context: _CompilationContext,
    section_name: str,
) -> OutputTarget:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr not in AUTHORING_TARGET_METHODS:
            raise PythonStepsValidationError(
                f"Unsupported target method '{node.func.attr}'",
                section_name=section_name,
                phase="compile",
            )
        if node.args or node.keywords:
            raise PythonStepsValidationError(
                f"{node.func.attr}() does not accept arguments",
                section_name=section_name,
                phase="compile",
            )
        base_target = _compile_target(node.func.value, context=context, section_name=section_name)
        return _apply_target_method(base_target, node.func.attr, section_name=section_name)

    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        raise PythonStepsValidationError(
            "Output targets must be File(...) or Var(...) calls",
            section_name=section_name,
            phase="compile",
        )

    func_name = node.func.id
    if func_name == "File":
        path = _first_required_path_arg(
            node,
            func_name,
            context=context,
            section_name=section_name,
        )
        return FileTarget(path=path, options=_keyword_literals(node, context=context))
    if func_name == "Var":
        name = _first_required_string_arg(
            node,
            func_name,
            context=context,
            section_name=section_name,
        )
        return VarTarget(name=name, options=_keyword_literals(node, context=context))

    raise PythonStepsValidationError(
        f"Unsupported output function '{func_name}'",
        section_name=section_name,
        phase="compile",
    )


def _apply_target_method(
    target: OutputTarget,
    method_name: str,
    *,
    section_name: str,
) -> OutputTarget:
    if method_name == "append":
        options = dict(target.options)
        options["mode"] = "append"
    elif method_name == "replace":
        options = dict(target.options)
        options["mode"] = "replace"
    elif method_name == "new":
        options = dict(target.options)
        options["mode"] = "new"
    else:
        raise PythonStepsValidationError(
            f"Unsupported target method '{method_name}'",
            section_name=section_name,
            phase="compile",
        )

    if isinstance(target, FileTarget):
        return FileTarget(path=target.path, options=options)
    return VarTarget(name=target.name, options=options)


def _keyword_map(call: ast.Call, *, section_name: str) -> dict[str, ast.AST]:
    kwargs: dict[str, ast.AST] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            raise PythonStepsValidationError(
                "Star-arguments are not allowed",
                section_name=section_name,
                phase="compile",
            )
        kwargs[keyword.arg] = keyword.value
    return kwargs


def _required_string(
    kwargs: dict[str, ast.AST],
    key: str,
    *,
    context: _CompilationContext,
    section_name: str,
) -> str:
    node = kwargs.get(key)
    if node is None:
        raise PythonStepsValidationError(
            f"{section_name} requires {key}=",
            section_name=section_name,
            phase="compile",
        )
    value = _resolve_literal(node, context=context)
    if not isinstance(value, str):
        raise PythonStepsValidationError(
            f"{key}= must resolve to a string",
            section_name=section_name,
            phase="compile",
        )
    return value


def _optional_string(
    kwargs: dict[str, ast.AST],
    key: str,
    *,
    context: _CompilationContext,
    section_name: str,
) -> str | None:
    node = kwargs.get(key)
    if node is None:
        return None
    value = _resolve_literal(node, context=context)
    if not isinstance(value, str):
        raise PythonStepsValidationError(
            f"{key}= must resolve to a string",
            section_name=section_name,
            phase="compile",
        )
    return value


def _first_required_string_arg(
    call: ast.Call,
    func_name: str,
    *,
    context: _CompilationContext,
    section_name: str,
) -> str:
    if len(call.args) != 1:
        raise PythonStepsValidationError(
            f"{func_name}(...) requires exactly one positional string argument",
            section_name=section_name,
            phase="compile",
        )
    value = _resolve_literal(call.args[0], context=context)
    if not isinstance(value, str):
        raise PythonStepsValidationError(
            f"{func_name}(...) argument must resolve to a string",
            section_name=section_name,
            phase="compile",
        )
    return value


def _first_required_path_arg(
    call: ast.Call,
    func_name: str,
    *,
    context: _CompilationContext,
    section_name: str,
) -> str:
    if len(call.args) != 1:
        raise PythonStepsValidationError(
            f"{func_name}(...) requires exactly one positional path argument",
            section_name=section_name,
            phase="compile",
        )
    value = _resolve_literal(call.args[0], context=context)
    if isinstance(value, PathValue):
        return str(value)
    if isinstance(value, str):
        if _contains_brace_pattern(value):
            raise PythonStepsValidationError(
                (
                    f"{func_name}(...) path arguments must use SDK date/path helpers instead of "
                    "brace substitutions. Use path.join(..., date.today(...)) rather than raw brace patterns."
                ),
                section_name=section_name,
                phase="compile",
            )
        return value
    raise PythonStepsValidationError(
        f"{func_name}(...) argument must resolve to a string or path.join(...) value",
        section_name=section_name,
        phase="compile",
    )


def _keyword_literals(
    call: ast.Call,
    *,
    context: _CompilationContext,
) -> dict[str, object]:
    compiled: dict[str, object] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            continue
        compiled[keyword.arg] = _resolve_literal(keyword.value, context=context)
    return compiled


def _collect_extras(
    kwargs: dict[str, ast.AST],
    *,
    handled: set[str],
    context: _CompilationContext,
) -> dict[str, object]:
    extras: dict[str, object] = {}
    for key, value in kwargs.items():
        if key in handled:
            continue
        extras[key] = _resolve_literal(value, context=context)
    return extras


def _is_sdk_constant_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_sdk_constant_expr(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (key is None or _is_sdk_constant_expr(key)) and _is_sdk_constant_expr(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in {"File", "Var"}
    return _is_sdk_helper_call(node) or isinstance(node.func, ast.Attribute)


def _compile_sdk_constant(
    node: ast.AST,
    *,
    context: _CompilationContext,
    section_name: str,
) -> object:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "File":
            path = _first_required_string_arg(
                node,
                "File",
                context=context,
                section_name=section_name,
            )
            return FileTarget(path=path, options=_keyword_literals(node, context=context))
        if node.func.id == "Var":
            name = _first_required_string_arg(
                node,
                "Var",
                context=context,
                section_name=section_name,
            )
            return VarTarget(name=name, options=_keyword_literals(node, context=context))

    if _is_sdk_helper_call(node):
        return _resolve_literal(node, context=context)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _compile_target(node, context=context, section_name=section_name)

    if isinstance(node, ast.List):
        return [_compile_sdk_constant(item, context=context, section_name=section_name) for item in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_compile_sdk_constant(item, context=context, section_name=section_name) for item in node.elts)

    return _resolve_literal(node, context=context)


def _resolve_literal(node: ast.AST, *, context: _CompilationContext) -> object:
    if isinstance(node, ast.Name):
        if node.id not in context.constants:
            raise PythonStepsValidationError(
                f"Unknown constant '{node.id}'",
                section_name=node.id,
                phase="semantic_validation",
            )
        return context.constants[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_resolve_literal(item, context=context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_resolve_literal(item, context=context) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _resolve_literal(key, context=context): _resolve_literal(value, context=context)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        operand = _resolve_literal(node.operand, context=context)
        if not isinstance(operand, int | float):
            raise PythonStepsValidationError(
                "Unary operators are only supported for numeric constants",
                section_name=context.block_label,
                phase="compile",
        )
        return +operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Call) and _is_sdk_helper_call(node):
        return _resolve_sdk_helper_call(node, context=context)
    raise PythonStepsValidationError(
        f"Unsupported literal expression '{type(node).__name__}'",
        section_name=context.block_label,
        phase="compile",
    )


def _resolve_sdk_helper_call(node: ast.Call, *, context: _CompilationContext) -> object:
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        raise PythonStepsValidationError(
            "Invalid SDK helper call",
            section_name=context.block_label,
            phase="compile",
        )
    owner = node.func.value.id
    method = node.func.attr
    if owner == "date":
        return _resolve_date_helper_call(node, method=method, context=context)
    if owner == "path":
        return _resolve_path_helper_call(node, method=method, context=context)
    raise PythonStepsValidationError(
        f"Unsupported SDK helper namespace '{owner}'",
        section_name=context.block_label,
        phase="compile",
    )


def _resolve_date_helper_call(
    node: ast.Call,
    *,
    method: str,
    context: _CompilationContext,
) -> DateValue:
    method_map = {
        "today": "today",
        "yesterday": "yesterday",
        "tomorrow": "tomorrow",
        "this_week": "this-week",
        "last_week": "last-week",
        "next_week": "next-week",
        "this_month": "this-month",
        "last_month": "last-month",
        "day_name": "day-name",
        "month_name": "month-name",
    }
    pattern = method_map.get(method)
    if pattern is None:
        raise PythonStepsValidationError(
            f"Unsupported date helper '{method}'",
            section_name=context.block_label,
            phase="compile",
        )
    fmt: str | None = None
    for keyword in node.keywords:
        if keyword.arg == "fmt":
            value = _resolve_literal(keyword.value, context=context)
            if value is not None and not isinstance(value, str):
                raise PythonStepsValidationError(
                    "date helper fmt= must resolve to a string",
                    section_name=context.block_label,
                    phase="compile",
                )
            fmt = value
    return DateValue(pattern=pattern, fmt=fmt)


def _resolve_path_helper_call(
    node: ast.Call,
    *,
    method: str,
    context: _CompilationContext,
) -> PathValue:
    if method != "join":
        raise PythonStepsValidationError(
            f"Unsupported path helper '{method}'",
            section_name=context.block_label,
            phase="compile",
        )
    segments: list[str | DateValue] = []
    for arg in node.args:
        value = _resolve_literal(arg, context=context)
        if isinstance(value, PathValue):
            segments.extend(value.segments)
            continue
        if isinstance(value, DateValue):
            segments.append(value)
            continue
        if isinstance(value, str):
            if _contains_brace_pattern(value):
                raise PythonStepsValidationError(
                    (
                        "path.join() string segments must be literal path parts, not raw brace substitutions. "
                        "Use date.*() helpers for dynamic segments."
                    ),
                    section_name=context.block_label,
                    phase="compile",
                )
            segments.append(value)
            continue
        raise PythonStepsValidationError(
            "path.join() arguments must resolve to strings, date.*() values, or nested path.join(...) values",
            section_name=context.block_label,
            phase="compile",
        )
    return PathValue(tuple(segments))


def _is_sdk_helper_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"date", "path"}
    )


def _contains_brace_pattern(value: str) -> bool:
    return "{" in value or "}" in value


def _workflow_name_from_run_call(call: ast.Call, *, section_name: str | None) -> str:
    if not isinstance(call.func, ast.Attribute):
        raise PythonStepsValidationError(
            "workflow.run() must be called on a workflow variable",
            section_name=section_name,
            phase="compile",
        )
    owner = call.func.value
    if not isinstance(owner, ast.Name):
        raise PythonStepsValidationError(
            "workflow.run() must target a named workflow variable",
            section_name=section_name,
            phase="compile",
        )
    return owner.id
