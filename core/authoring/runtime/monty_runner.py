"""Minimal Monty runtime wrapper for the experimental authoring surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic_monty import Monty, run_monty_async

from core.authoring.builtins import create_builtin_registry
from core.authoring.contracts import (
    AuthoringCapabilityScope,
    AuthoringExecutionContext,
    AuthoringHost,
)
from core.authoring.registry import AuthoringCapabilityRegistry
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-monty")


class AuthoringMontyExecutionError(RuntimeError):
    """Raised when Monty-backed authoring execution fails."""


@dataclass(frozen=True)
class AuthoringMontyExecutionResult:
    """Structured result from one Monty-backed authoring execution."""

    value: Any
    prints: tuple[str, ...] = ()
    enabled_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PrintCapture:
    lines: list[str] = field(default_factory=list)

    def callback(self, _channel: str, text: str) -> None:
        self.lines.append(text)


async def run_authoring_monty(
    *,
    workflow_id: str,
    code: str,
    host: AuthoringHost,
    frontmatter: Mapping[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    script_name: str = "main.py",
    type_check: bool = False,
    registry: AuthoringCapabilityRegistry | None = None,
) -> AuthoringMontyExecutionResult:
    """Execute one experimental authoring artifact with Monty."""
    capability_scope = AuthoringCapabilityScope.from_frontmatter(frontmatter)
    runtime_registry = registry or create_builtin_registry()
    context = AuthoringExecutionContext(
        workflow_id=workflow_id,
        host=host,
        scope=capability_scope,
    )
    external_functions = runtime_registry.build_external_functions(
        context=context,
        scope=capability_scope,
    )
    reserved_inputs = dict(host.get_monty_inputs())
    effective_inputs = {**reserved_inputs, **(inputs or {})}
    capture = _PrintCapture()

    logger.info(
        "authoring_monty_execution_started",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "enabled_capabilities": sorted(capability_scope.enabled),
            "type_check": type_check,
        },
    )
    logger.set_sinks(["validation"]).info(
        "authoring_monty_execution_started",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "enabled_capabilities": sorted(capability_scope.enabled),
            "type_check": type_check,
        },
    )

    try:
        runner = Monty(
            code,
            script_name=script_name,
            inputs=sorted(effective_inputs) if effective_inputs else None,
            type_check=type_check,
        )
        for dataclass_type in host.get_monty_dataclasses():
            runner.register_dataclass(dataclass_type)
        if type_check:
            runner.type_check()

        value = await run_monty_async(
            runner,
            inputs=effective_inputs or None,
            external_functions=external_functions,
            print_callback=capture.callback,
        )
    except Exception as exc:
        logger.error(
            "authoring_monty_execution_failed",
            data={
                "workflow_id": workflow_id,
                "script_name": script_name,
                "enabled_capabilities": sorted(capability_scope.enabled),
                "error_message": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        logger.set_sinks(["validation"]).error(
            "authoring_monty_execution_failed",
            data={
                "workflow_id": workflow_id,
                "script_name": script_name,
                "enabled_capabilities": sorted(capability_scope.enabled),
                "error_message": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise AuthoringMontyExecutionError(
            f"Monty execution failed for '{workflow_id}': {exc}"
        ) from exc

    logger.info(
        "authoring_monty_execution_completed",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "enabled_capabilities": sorted(capability_scope.enabled),
            "printed_line_count": len(capture.lines),
        },
    )
    logger.set_sinks(["validation"]).info(
        "authoring_monty_execution_completed",
        data={
            "workflow_id": workflow_id,
            "script_name": script_name,
            "enabled_capabilities": sorted(capability_scope.enabled),
            "printed_line_count": len(capture.lines),
        },
    )
    return AuthoringMontyExecutionResult(
        value=value,
        prints=tuple(capture.lines),
        enabled_capabilities=tuple(sorted(capability_scope.enabled)),
    )
