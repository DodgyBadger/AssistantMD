"""Shared model execution mode resolution.

Centralizes how model aliases map to execution behavior so workflow, chat,
and context systems stay consistent (for example, @model none => skip mode).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from core.directives.parser import DirectiveValueParser


ModelExecutionMode = Literal["llm", "skip"]


@dataclass(frozen=True)
class ModelExecutionSpec:
    """Resolved execution behavior for a model alias string."""

    mode: ModelExecutionMode
    base_alias: Optional[str]
    raw_alias: Optional[str]


def resolve_model_execution_spec(model_alias: str | None) -> ModelExecutionSpec:
    """Resolve model alias into execution mode and normalized base alias.

    Rules:
    - Empty/None alias => llm mode (caller default model handling applies)
    - Base alias 'none' => skip mode
    - Any other alias => llm mode
    """

    if model_alias is None:
        return ModelExecutionSpec(mode="llm", base_alias=None, raw_alias=None)

    raw = str(model_alias).strip()
    if not raw:
        return ModelExecutionSpec(mode="llm", base_alias=None, raw_alias=raw)

    base_alias, _ = DirectiveValueParser.parse_value_with_parameters(raw)
    normalized_base_alias = DirectiveValueParser.normalize_string(
        base_alias, to_lower=True
    )

    if normalized_base_alias == "none":
        return ModelExecutionSpec(
            mode="skip",
            base_alias=normalized_base_alias,
            raw_alias=raw,
        )

    return ModelExecutionSpec(
        mode="llm",
        base_alias=normalized_base_alias,
        raw_alias=raw,
    )

