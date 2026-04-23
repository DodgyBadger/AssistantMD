"""Chat context-template history processor capability."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from pydantic_ai.capabilities import HistoryProcessor

from core.authoring.context_manager import (
    ContextTemplateExecutionError,
    build_context_manager_history_processor,
)
from core.logger import UnifiedLogger
from core.settings.store import get_general_settings


logger = UnifiedLogger(tag="chat-executor")


def build_chat_context_capability(
    *,
    vault_name: str,
    vault_path: str,
    session_id: str,
    model_alias: str,
    context_template: str | None,
    history_processor_factory: Callable[..., Any] = build_context_manager_history_processor,
) -> HistoryProcessor[Any] | None:
    """Build a context-template history processor capability when available."""
    template_candidates = build_context_template_candidates(context_template)
    if not template_candidates:
        return None

    for candidate in template_candidates:
        try:
            processor = history_processor_factory(
                session_id=session_id,
                vault_name=vault_name,
                vault_path=vault_path,
                model_alias=model_alias,
                template_name=candidate,
            )
            return HistoryProcessor(_normalize_history_processor(processor))
        except ContextTemplateExecutionError as exc:
            logger.warning(
                "Context template failed, trying next in fallback chain",
                data=build_context_template_error_details(
                    vault_name=vault_name,
                    session_id=session_id,
                    template_name=exc.template_name,
                    phase=exc.phase,
                    template_pointer=exc.template_pointer,
                )
                | {"error": str(exc), "candidate": candidate},
            )

    logger.warning(
        "All context template candidates failed; proceeding without context template",
        data={
            "vault_name": vault_name,
            "session_id": session_id,
            "tried": template_candidates,
        },
    )
    return None


def _normalize_history_processor(processor: Any) -> Any:
    """Accept old one-argument test processors and current two-argument processors."""
    try:
        parameter_count = len(inspect.signature(processor).parameters)
    except (TypeError, ValueError):
        return processor
    if parameter_count != 1:
        return processor

    async def wrapped(messages: Any) -> Any:
        result = processor(messages)
        if inspect.isawaitable(result):
            return await result
        return result

    return wrapped


def build_context_template_error_details(
    *,
    vault_name: str,
    session_id: str,
    template_name: str,
    phase: str,
    template_pointer: str,
) -> dict[str, Any]:
    return {
        "vault_name": vault_name,
        "session_id": session_id,
        "template_name": template_name,
        "phase": phase,
        "template_pointer": template_pointer,
    }


def build_context_template_candidates(context_template: str | None) -> list[str]:
    """Resolve the chat context-template fallback chain."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _append(value: str | None) -> None:
        normalized = _normalize_context_template_selection(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    _append(context_template)
    _append(_get_global_default_template())
    _append("default.md")
    return candidates


def _normalize_context_template_selection(context_template: str | None) -> str | None:
    """Return a selected template name or None for unmanaged chat."""
    if context_template is None:
        return None
    normalized = str(context_template).strip()
    return normalized or None


def _get_global_default_template() -> str | None:
    try:
        entry = get_general_settings().get("default_context_script")
        if entry and entry.value:
            return str(entry.value).strip() or None
    except Exception:
        pass
    return None
