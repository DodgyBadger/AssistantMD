"""Definition and execution for the import_content(...) Monty helper."""

from __future__ import annotations

from typing import Any

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
)
from core.authoring.helpers.common import build_capability, placeholder_contract


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="import_content",
        doc="Import external content through the host ingestion pipeline.",
        contract=placeholder_contract(
            "import_content",
            "import_content(*, source: str, options: dict | None = None)",
        ),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> Any:
    del call, context
    raise NotImplementedError("import_content is not implemented for the Monty MVP host")
