"""Load-time parsing and safety checks for python_steps workflows."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from core.logger import UnifiedLogger

if TYPE_CHECKING:
    from core.workflow.python_steps.models import CompiledPythonStepsWorkflow


logger = UnifiedLogger(tag="python-steps")

PYTHON_FENCE_PATTERN = re.compile(r"```python\s*\n(.*?)\n```", re.DOTALL)
ALLOWED_CALL_NAMES = {
    "append_var",
    "branch",
    "file",
    "files",
    "foreach",
    "from_field",
    "run_step",
    "step",
    "var",
    "when",
    "write",
}
ALLOWED_EXPR_NODES = (
    ast.Call,
    ast.Constant,
    ast.Dict,
    ast.Expression,
    ast.keyword,
    ast.List,
    ast.Load,
    ast.Name,
    ast.Tuple,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
)


@dataclass(frozen=True)
class ParsedPythonStepBlock:
    """Single validated python step block discovered in markdown."""

    section_name: str
    code: str


@dataclass(frozen=True)
class ParsedPythonStepWorkflow:
    """Validated set of python step blocks for a workflow file."""

    workflow_id: str
    blocks: list[ParsedPythonStepBlock]


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
    del file_path, validated_config

    workflow_sections = {
        name: content
        for name, content in sections.items()
        if name != "__FRONTMATTER_CONFIG__"
    }

    try:
        workflow = _parse_python_step_workflow(
            workflow_id=workflow_id,
            sections=workflow_sections,
        )
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
            "step_count": len(workflow.blocks),
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
            "step_names": sorted(compiled.steps.keys()),
        },
    )
    return compiled


def _parse_python_step_workflow(
    *,
    workflow_id: str,
    sections: dict[str, str],
) -> ParsedPythonStepWorkflow:
    blocks: list[ParsedPythonStepBlock] = []

    for section_name, content in sections.items():
        if not content.strip():
            continue

        matches = PYTHON_FENCE_PATTERN.findall(content)
        if not matches:
            continue
        if len(matches) > 1:
            raise PythonStepsValidationError(
                "Python step sections must contain exactly one fenced ```python``` block",
                section_name=section_name,
                phase="markdown_structure",
            )

        code = matches[0].strip()
        _validate_python_block(code, section_name=section_name)
        blocks.append(ParsedPythonStepBlock(section_name=section_name, code=code))

    if not blocks:
        raise PythonStepsValidationError(
            "python_steps workflows must include at least one fenced ```python``` step block",
            section_name=None,
            phase="markdown_structure",
        )

    return ParsedPythonStepWorkflow(workflow_id=workflow_id, blocks=blocks)


def _validate_python_block(code: str, *, section_name: str) -> None:
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

    if len(module.body) != 1 or not isinstance(module.body[0], ast.Expr):
        raise PythonStepsValidationError(
            "Python step blocks must contain exactly one top-level expression",
            section_name=section_name,
            phase="python_syntax",
        )

    expression = module.body[0].value
    if not isinstance(expression, ast.Call) or not _is_name(expression.func, "step"):
        raise PythonStepsValidationError(
            "Python step blocks must call step(...) as the top-level expression",
            section_name=section_name,
            phase="python_syntax",
        )

    _validate_expr(expression, section_name=section_name)


def _validate_expr(node: ast.AST, *, section_name: str) -> None:
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise PythonStepsValidationError(
                "Only direct SDK function calls are allowed in python step blocks",
                section_name=section_name,
                phase="ast_safety",
            )
        if node.func.id not in ALLOWED_CALL_NAMES:
            raise PythonStepsValidationError(
                f"Unsupported SDK function '{node.func.id}'",
                section_name=section_name,
                phase="ast_safety",
            )
        for arg in node.args:
            _validate_expr(arg, section_name=section_name)
        for keyword in node.keywords:
            if keyword.arg is None:
                raise PythonStepsValidationError(
                    "Star-arguments are not allowed in python step blocks",
                    section_name=section_name,
                    phase="ast_safety",
                )
            _validate_expr(keyword.value, section_name=section_name)
        return

    if isinstance(node, ast.Name):
        if node.id not in ALLOWED_CALL_NAMES:
            raise PythonStepsValidationError(
                f"Unsupported name '{node.id}'",
                section_name=section_name,
                phase="ast_safety",
            )
        return

    if isinstance(node, ast.List | ast.Tuple):
        for item in node.elts:
            _validate_expr(item, section_name=section_name)
        return

    if isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None:
                _validate_expr(key, section_name=section_name)
        for value in node.values:
            _validate_expr(value, section_name=section_name)
        return

    if isinstance(node, ast.keyword):
        _validate_expr(node.value, section_name=section_name)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.UAdd | ast.USub):
            raise PythonStepsValidationError(
                "Only unary plus/minus are allowed in python step blocks",
                section_name=section_name,
                phase="ast_safety",
            )
        _validate_expr(node.operand, section_name=section_name)
        return

    if isinstance(node, ast.Constant):
        return

    if not isinstance(node, ALLOWED_EXPR_NODES):
        raise PythonStepsValidationError(
            f"Unsupported Python syntax node '{type(node).__name__}'",
            section_name=section_name,
            phase="ast_safety",
        )


def _is_name(node: ast.AST, expected: str) -> bool:
    return isinstance(node, ast.Name) and node.id == expected


def _format_parse_error(exc: PythonStepsValidationError) -> str:
    if exc.section_name:
        return f"{exc} [section: {exc.section_name}, phase: {exc.phase}]"
    return f"{exc} [phase: {exc.phase}]"
