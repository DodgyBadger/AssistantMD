"""Definition and execution for the finish(...) Monty helper."""

from __future__ import annotations

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    AuthoringFinishSignal,
)
from core.authoring.helpers.common import build_capability
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="finish",
        doc="End execution intentionally with a structured terminal status.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> None:
    status, reason = _parse_call(call)
    logger.info(
        "authoring_finish_requested",
        data={
            "workflow_id": context.workflow_id,
            "status": status,
            "reason": reason,
        },
    )
    logger.set_sinks(["validation"]).info(
        "authoring_finish_requested",
        data={
            "workflow_id": context.workflow_id,
            "status": status,
            "reason": reason,
        },
    )
    raise AuthoringFinishSignal(status=status, reason=reason)


def _parse_call(call: AuthoringCapabilityCall) -> tuple[str, str]:
    if call.args:
        raise ValueError("finish only supports keyword arguments")
    unknown = sorted(set(call.kwargs) - {"status", "reason"})
    if unknown:
        raise ValueError(f"Unsupported finish arguments: {', '.join(unknown)}")
    status = str(call.kwargs.get("status") or "completed").strip().lower()
    if status not in {"completed", "skipped"}:
        raise ValueError("finish status must be one of: completed, skipped")
    reason = str(call.kwargs.get("reason") or "").strip()
    return status, reason


def _contract() -> dict[str, object]:
    return {
        "signature": 'finish(*, status: str = "completed", reason: str | None = None)',
        "summary": (
            "End execution intentionally with a terminal status instead of raising an error."
        ),
        "arguments": {
            "status": {
                "type": "string",
                "required": False,
                "description": "Terminal status. Supported values are completed and skipped.",
            },
            "reason": {
                "type": "string",
                "required": False,
                "description": "Optional human-readable reason recorded in execution logs and results.",
            },
        },
        "return_shape": {
            "status": "Resolved terminal status.",
            "reason": "Structured reason string when provided.",
        },
        "examples": [
            {
                "code": 'await finish(status="skipped", reason="No inputs matched today.")',
                "description": "Exit early without treating the workflow as a failure.",
            },
        ],
    }
