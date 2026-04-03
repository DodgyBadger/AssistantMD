"""Load-time parsing and safety checks for python_steps workflows."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.authoring import AUTHORING_PRIMITIVE_NAMES, AUTHORING_TARGET_METHODS
from core.logger import UnifiedLogger
from core.utils.frontmatter import parse_simple_frontmatter

if TYPE_CHECKING:
    from core.workflow.python_steps.models import CompiledPythonStepsWorkflow


logger = UnifiedLogger(tag="python-steps")

PYTHON_FENCE_PATTERN = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
ALLOWED_LITERAL_NODES = (
    ast.Constant,
    ast.Dict,
    ast.List,
    ast.Load,
    ast.Name,
    ast.Tuple,
    ast.UAdd,
    ast.UnaryOp,
    ast.USub,
)

@dataclass(frozen=True)
class ParsedPythonStepWorkflow:
    """Validated python_steps workflow source extracted from markdown."""

    workflow_id: str
    code: str
    block_count: int
    block_label: str | None = None


class PythonStepsValidationError(ValueError):
    """Workflow-definition error with section and phase context."""

    def __init__(self, message: str, *, section_name: str | None, phase: str) -> None:
        super().__init__(message)
        self.section_name = section_name
        self.phase = phase


def validate_python_steps_workflow_definition(
    *,
    workflow_id: str,
    file_path: str,
    sections: dict[str, Any],
    validated_config: dict[str, Any],
) -> "CompiledPythonStepsWorkflow":
    """Validate markdown structure and Python AST constraints for python_steps."""
    del sections, validated_config

    try:
        workflow = _parse_python_step_workflow(workflow_id=workflow_id, file_path=file_path)
    except PythonStepsValidationError as exc:
        logger.set_sinks(["validation"]).error(
            "python_steps_parse_failed",
            data={
                "workflow_id": workflow_id,
                "section": exc.section_name,
                "phase": exc.phase,
                "error": str(exc),
            },
        )
        raise ValueError(_format_parse_error(exc)) from exc

    logger.set_sinks(["validation"]).info(
        "python_steps_blocks_parsed",
        data={
            "workflow_id": workflow_id,
            "block_count": workflow.block_count,
        },
    )

    try:
        from core.workflow.python_steps.compiler import compile_python_steps_workflow

        compiled = compile_python_steps_workflow(workflow)
    except PythonStepsValidationError as exc:
        logger.set_sinks(["validation"]).error(
            "python_steps_semantic_validation_failed",
            data={
                "workflow_id": workflow_id,
                "step_name": exc.section_name,
                "error": str(exc),
            },
        )
        raise ValueError(_format_parse_error(exc)) from exc

    logger.set_sinks(["validation"]).info(
        "python_steps_compiled",
        data={
            "workflow_id": workflow_id,
            "step_names": compiled.workflow.step_names,
        },
    )
    return compiled


def parse_python_steps_workflow_text(
    *,
    workflow_id: str,
    content: str,
) -> ParsedPythonStepWorkflow:
    """Parse and validate python_steps workflow text without reading a file."""
    _frontmatter, body = parse_simple_frontmatter(
        content,
        require_frontmatter=True,
        missing_error="Workflow file must start with YAML frontmatter (---)",
    )
    return _parse_python_step_workflow_body(workflow_id=workflow_id, body=body)


def _parse_python_step_workflow(
    *,
    workflow_id: str,
    file_path: str,
) -> ParsedPythonStepWorkflow:
    with open(file_path, "r", encoding="utf-8") as handle:
        content = handle.read()

    _frontmatter, body = parse_simple_frontmatter(
        content,
        require_frontmatter=True,
        missing_error="Workflow file must start with YAML frontmatter (---)",
    )
    return _parse_python_step_workflow_body(workflow_id=workflow_id, body=body)


def _parse_python_step_workflow_body(
    *,
    workflow_id: str,
    body: str,
) -> ParsedPythonStepWorkflow:
    matches = list(PYTHON_FENCE_PATTERN.finditer(body))
    if not matches:
        raise PythonStepsValidationError(
            "python_steps workflows must include exactly one fenced ```python``` block",
            section_name=None,
            phase="markdown_structure",
        )
    if len(matches) > 1:
        raise PythonStepsValidationError(
            "python_steps workflows support exactly one fenced ```python``` block",
            section_name=None,
            phase="markdown_structure",
        )

    code = matches[0].group(1).strip()
    block_label = _nearest_heading(body, matches[0].start())
    _validate_python_block(code, section_name=block_label)
    return ParsedPythonStepWorkflow(
        workflow_id=workflow_id,
        code=code,
        block_count=len(matches),
        block_label=block_label,
    )


def _validate_python_block(code: str, *, section_name: str | None) -> None:
    try:
        module = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        message = exc.msg
        if exc.lineno is not None:
            message = f"{message} at line {exc.lineno}"
        raise PythonStepsValidationError(
            f"Invalid Python syntax: {message}",
            section_name=section_name,
            phase="python_syntax",
        ) from exc

    if not module.body:
        raise PythonStepsValidationError(
            "Python workflow block cannot be empty",
            section_name=section_name,
            phase="python_syntax",
        )

    for statement in module.body[:-1]:
        _validate_top_level_statement(statement, section_name=section_name)

    terminal = module.body[-1]
    if not _is_terminal_run_call(terminal):
        raise PythonStepsValidationError(
            "Python workflow blocks must end with workflow.run()",
            section_name=section_name,
            phase="python_syntax",
        )


def _validate_top_level_statement(statement: ast.stmt, *, section_name: str | None) -> None:
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        raise PythonStepsValidationError(
            "Top-level statements must be simple assignments before workflow.run()",
            section_name=section_name,
            phase="ast_safety",
        )

    target = statement.targets[0]
    if not isinstance(target, ast.Name):
        raise PythonStepsValidationError(
            "Top-level assignments must target a simple name",
            section_name=section_name,
            phase="ast_safety",
        )

    _validate_assignment_value(statement.value, section_name=section_name)


def _validate_assignment_value(node: ast.AST, *, section_name: str | None) -> None:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in AUTHORING_PRIMITIVE_NAMES:
            _validate_call_arguments(node, section_name=section_name)
            return
        if _is_target_method_call(node):
            _validate_target_method_call(node, section_name=section_name)
            return
        raise PythonStepsValidationError(
            "Only Step(...), Workflow(...), File(...), Var(...), and target methods are allowed",
            section_name=section_name,
            phase="ast_safety",
        )

    _validate_literal_expr(node, section_name=section_name)


def _validate_call_arguments(node: ast.Call, *, section_name: str | None) -> None:
    for arg in node.args:
        _validate_argument_expr(arg, section_name=section_name)
    for keyword in node.keywords:
        if keyword.arg is None:
            raise PythonStepsValidationError(
                "Star-arguments are not allowed in python_steps workflows",
                section_name=section_name,
                phase="ast_safety",
            )
        _validate_argument_expr(keyword.value, section_name=section_name)


def _validate_argument_expr(node: ast.AST, *, section_name: str | None) -> None:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in AUTHORING_PRIMITIVE_NAMES:
            _validate_call_arguments(node, section_name=section_name)
            return
        if _is_target_method_call(node):
            _validate_target_method_call(node, section_name=section_name)
            return
        raise PythonStepsValidationError(
            "Unsupported SDK call in workflow block",
            section_name=section_name,
            phase="ast_safety",
        )

    _validate_literal_expr(node, section_name=section_name)


def _validate_target_method_call(node: ast.Call, *, section_name: str | None) -> None:
    if not isinstance(node.func, ast.Attribute):
        raise PythonStepsValidationError(
            "Invalid target method call",
            section_name=section_name,
            phase="ast_safety",
        )
    if node.func.attr not in AUTHORING_TARGET_METHODS:
        raise PythonStepsValidationError(
            f"Unsupported target method '{node.func.attr}'",
            section_name=section_name,
            phase="ast_safety",
        )
    if node.args or node.keywords:
        raise PythonStepsValidationError(
            f"{node.func.attr}() does not accept arguments",
            section_name=section_name,
            phase="ast_safety",
        )
    if not isinstance(node.func.value, ast.Call):
        raise PythonStepsValidationError(
            "Target methods must be called on File(...) or Var(...)",
            section_name=section_name,
            phase="ast_safety",
        )
    _validate_assignment_value(node.func.value, section_name=section_name)


def _validate_literal_expr(node: ast.AST, *, section_name: str | None) -> None:
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.List | ast.Tuple):
        for item in node.elts:
            _validate_argument_expr(item, section_name=section_name)
        return
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None:
                _validate_literal_expr(key, section_name=section_name)
        for value in node.values:
            _validate_argument_expr(value, section_name=section_name)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.UAdd | ast.USub):
            raise PythonStepsValidationError(
                "Only unary plus/minus are allowed in python_steps workflows",
                section_name=section_name,
                phase="ast_safety",
            )
        _validate_literal_expr(node.operand, section_name=section_name)
        return
    if isinstance(node, ast.Constant):
        return
    if not isinstance(node, ALLOWED_LITERAL_NODES):
        raise PythonStepsValidationError(
            f"Unsupported Python syntax node '{type(node).__name__}'",
            section_name=section_name,
            phase="ast_safety",
        )


def _is_target_method_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id in {"File", "Var"}
    )


def _is_terminal_run_call(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Expr):
        return False
    value = statement.value
    return (
        isinstance(value, ast.Call)
        and not value.args
        and not value.keywords
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "run"
        and isinstance(value.func.value, ast.Name)
    )


def _nearest_heading(markdown_body: str, code_start: int) -> str | None:
    preceding = markdown_body[:code_start]
    matches = re.findall(r"^##\s+(.+?)\s*$", preceding, re.MULTILINE)
    if not matches:
        return None
    return matches[-1].strip()


def _format_parse_error(exc: PythonStepsValidationError) -> str:
    prefix = exc.phase.replace("_", " ").capitalize()
    if exc.section_name:
        return f"{prefix} in section '{exc.section_name}': {exc}"
    return f"{prefix}: {exc}"
