"""
Context manager for assembling chat history via Monty authoring templates.

Merged from core/context/manager_types.py, core/context/manager_helpers.py,
and core/context/manager.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from core.authoring.contracts import AssembleContextResult, ContextMessage
from core.authoring.template_discovery import load_template
from core.authoring.template_loader import parse_authoring_template_text
from core.authoring.runtime import AuthoringMontyExecutionError, WorkflowAuthoringHost, run_authoring_monty
from core.authoring.cache import add_context_summary, upsert_session
from core.constants import VALID_WEEK_DAYS
from core.logger import UnifiedLogger
from core.runtime.state import get_runtime_context, has_runtime_context
from core.utils.hash import hash_file_content
from core.utils.messages import extract_role_and_text

logger = UnifiedLogger(tag="context-manager")


# ---------------------------------------------------------------------------
# ContextTemplateError
# ---------------------------------------------------------------------------

class ContextTemplateError(ValueError):
    """Template-facing context manager error with section/pointer metadata."""

    def __init__(
        self,
        message: str,
        *,
        template_pointer: str,
        section_name: Optional[str] = None,
        phase: Optional[str] = None,
    ):
        super().__init__(message)
        self.template_pointer = template_pointer
        self.section_name = section_name
        self.phase = phase


class ContextTemplateExecutionError(RuntimeError):
    """Raised when a selected context template cannot be used for chat execution."""

    def __init__(
        self,
        message: str,
        *,
        template_name: str,
        phase: str,
        template_pointer: str,
    ):
        super().__init__(message)
        self.template_name = template_name
        self.phase = phase
        self.template_pointer = template_pointer


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def normalize_input_file_lists(input_file_data: Any) -> List[List[Dict[str, Any]]]:
    if not input_file_data:
        return []
    if isinstance(input_file_data, list) and input_file_data and isinstance(input_file_data[0], dict):
        return [input_file_data]
    if isinstance(input_file_data, list):
        return input_file_data
    return []


def count_input_files(input_file_data: Any) -> Dict[str, int]:
    file_lists = normalize_input_file_lists(input_file_data)
    if not file_lists:
        return {"total": 0, "refs_only": 0, "missing": 0}
    total = 0
    refs_only = 0
    missing = 0
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            if file_data.get("manifest"):
                continue
            total += 1
            if file_data.get("refs_only"):
                refs_only += 1
            if file_data.get("found") is False:
                missing += 1
    return {"total": total, "refs_only": refs_only, "missing": missing}


def summarize_input_files(input_file_data: Any, preview_limit: int = 200) -> List[Dict[str, Any]]:
    file_lists = normalize_input_file_lists(input_file_data)
    if not file_lists:
        return []
    summaries: List[Dict[str, Any]] = []
    for file_list in file_lists:
        for file_data in file_list:
            if not isinstance(file_data, dict):
                continue
            if file_data.get("manifest"):
                continue
            content = ""
            if file_data.get("found") and not file_data.get("refs_only"):
                content = file_data.get("content", "") or ""
            preview = None
            if content:
                preview = content.strip().replace("\n", " ")
                if len(preview) > preview_limit:
                    preview = f"{preview[:preview_limit - 1]}…"
            summaries.append(
                {
                    "filepath": file_data.get("filepath"),
                    "found": file_data.get("found", True),
                    "refs_only": file_data.get("refs_only", False),
                    "content_length": len(content),
                    "content_preview": preview,
                }
            )
    return summaries


def hash_output(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hash_file_content(value, length=12)


def resolve_cache_now(run_context: RunContext[Any]) -> datetime:
    deps = getattr(run_context, "deps", None)
    now_override = getattr(deps, "context_manager_now", None) if deps is not None else None
    if isinstance(now_override, datetime):
        return now_override
    if isinstance(now_override, str):
        try:
            return datetime.fromisoformat(now_override)
        except ValueError:
            pass
    if has_runtime_context():
        try:
            runtime = get_runtime_context()
            raw_value = (runtime.config.features or {}).get("context_manager_now")
            if isinstance(raw_value, datetime):
                return raw_value
            if isinstance(raw_value, str):
                return datetime.fromisoformat(raw_value)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to read context_manager_now from runtime config; using current time",
                data={"error": str(exc)},
            )
    return datetime.now(timezone.utc)


def _frontmatter_value_with_alias(
    frontmatter: Optional[Dict[str, Any]],
    canonical_key: str,
    alias_key: str,
) -> Any:
    """Get a frontmatter value supporting both canonical and alias keys."""
    if not frontmatter:
        return None

    canonical_present = canonical_key in frontmatter
    alias_present = alias_key in frontmatter
    canonical_value = frontmatter.get(canonical_key)
    alias_value = frontmatter.get(alias_key)

    if canonical_present and alias_present and canonical_value != alias_value:
        logger.warning(
            "Conflicting frontmatter keys; preferring canonical key",
            data={
                "canonical_key": canonical_key,
                "alias_key": alias_key,
                "canonical_value": canonical_value,
                "alias_value": alias_value,
            },
        )

    if canonical_present:
        return canonical_value
    if alias_present:
        return alias_value
    return None


def resolve_week_start_day(frontmatter: Optional[Dict[str, Any]]) -> int:
    """
    Resolve week_start_day from template frontmatter.

    Returns 0=Monday .. 6=Sunday, defaulting to Monday on missing/invalid values.
    """
    if not frontmatter:
        return 0
    raw_value = _frontmatter_value_with_alias(frontmatter, "week_start_day", "week-start-day")
    if raw_value is None:
        return 0
    if isinstance(raw_value, int) and 0 <= raw_value <= 6:
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in VALID_WEEK_DAYS:
            return VALID_WEEK_DAYS.index(normalized)
    logger.warning(
        "Invalid week_start_day in context template; defaulting to monday",
        data={"value": raw_value},
    )
    return 0


def find_last_user_idx(msgs: List[ModelMessage]) -> Optional[int]:
    for idx in range(len(msgs) - 1, -1, -1):
        m = msgs[idx]
        role = getattr(m, "role", None)
        if role and role.lower() == "user":
            return idx
        if isinstance(m, ModelRequest) and _model_request_has_user_prompt(m):
            return idx
    return None


def _model_request_has_user_prompt(message: ModelRequest) -> bool:
    parts = getattr(message, "parts", None) or ()
    for part in parts:
        if isinstance(part, UserPromptPart):
            return True
    return False


def _context_message_to_model_message(message: ContextMessage) -> ModelMessage:
    role = (message.role or "system").strip().lower()
    content = message.content or ""
    if role == "assistant":
        return ModelResponse(parts=[TextPart(content=content)])
    if role == "user":
        return ModelRequest(parts=[UserPromptPart(content=content)])
    return ModelRequest(parts=[SystemPromptPart(content=content)])


def _normalize_authoring_context_result(value: Any) -> AssembleContextResult:
    if isinstance(value, AssembleContextResult):
        return value
    if isinstance(value, dict):
        messages = value.get("messages", ())
        instructions = value.get("instructions", ())
        normalized_messages: list[ContextMessage] = []
        if not isinstance(messages, (list, tuple)):
            raise ValueError("assemble_context result must expose 'messages' as a list or tuple")
        for item in messages:
            if isinstance(item, ContextMessage):
                normalized_messages.append(item)
                continue
            if isinstance(item, dict):
                normalized_messages.append(
                    ContextMessage(
                        role=str(item.get("role") or "system"),
                        content=str(item.get("content") or ""),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
                continue
            raise ValueError("assemble_context result messages must contain ContextMessage or dict values")
        normalized_instructions: list[str] = []
        if isinstance(instructions, (list, tuple)):
            for item in instructions:
                text = str(item).strip()
                if text:
                    normalized_instructions.append(text)
        return AssembleContextResult(
            messages=tuple(normalized_messages),
            instructions=tuple(normalized_instructions),
        )
    raise ValueError("Authoring context template must return AssembleContextResult or an equivalent dictionary")


def _combined_context_text(messages: Sequence[ContextMessage]) -> str:
    return "\n\n".join(
        f"{(message.role or 'system').strip().lower()}: {message.content}"
        for message in messages
        if (message.content or "").strip()
    ).strip()


def _prompt_to_user_message(prompt: Any) -> ModelMessage | None:
    if isinstance(prompt, str):
        text = prompt.strip()
        if not text:
            return None
        return ModelRequest(parts=[UserPromptPart(content=text)])
    return None


def _compiled_history_includes_latest_user(
    messages: Sequence[ContextMessage],
    latest_user_message: ModelMessage | None,
) -> bool:
    if latest_user_message is None:
        return False
    latest_role, latest_text = extract_role_and_text(latest_user_message)
    if latest_role != "user" or not latest_text:
        return False
    for message in reversed(messages):
        if message.role == "user" and message.content == latest_text:
            return True
    return False


def _latest_turn_messages(messages: Sequence[ModelMessage]) -> List[ModelMessage]:
    """Return the active turn suffix starting at the latest real user prompt."""
    last_user_idx = find_last_user_idx(list(messages))
    if last_user_idx is None:
        return list(messages)
    return list(messages[last_user_idx:])


async def _build_authoring_context_history(
    *,
    run_context: RunContext[Any],
    messages: List[ModelMessage],
    session_id: str,
    vault_name: str,
    vault_path: str,
    template,
    source,
) -> List[ModelMessage]:
    if not messages:
        return []

    latest_turn_messages = _latest_turn_messages(messages)
    latest_user_message = latest_turn_messages[0] if latest_turn_messages else None

    workflow_id = f"{vault_name}/context/{template.name}/{session_id}"
    reference_date = resolve_cache_now(run_context)
    current_prompt_message = _prompt_to_user_message(run_context.prompt)
    history_for_memory = list(messages)
    if current_prompt_message is not None:
        prompt_role, prompt_text = extract_role_and_text(current_prompt_message)
        last_role, last_text = ("", "")
        if history_for_memory:
            last_role, last_text = extract_role_and_text(history_for_memory[-1])
        if prompt_role != last_role or prompt_text != last_text:
            history_for_memory.append(current_prompt_message)
    host = WorkflowAuthoringHost(
        workflow_id=workflow_id,
        vault_path=vault_path,
        reference_date=reference_date,
        week_start_day=resolve_week_start_day(template.frontmatter),
        session_key=session_id,
        chat_session_id=session_id,
        message_history=history_for_memory,
    )

    try:
        result = await run_authoring_monty(
            workflow_id=workflow_id,
            code=source.code,
            host=host,
            inputs={},
            script_name=template.name,
        )
    except AuthoringMontyExecutionError as exc:
        logger.warning(
            "Context authoring execution failed in history processor",
            data={
                "error": str(exc),
                "template_name": template.name,
                "phase": "authoring_run",
                "template_pointer": source.docstring_summary or "```python``` block",
            },
        )
        raise ContextTemplateExecutionError(
            (
                f"Context template '{template.name}' failed during execution. "
                "Fix the template or select No template to continue without context management. "
                f"Details: {exc}"
            ),
            template_name=template.name,
            phase="authoring_run",
            template_pointer=source.docstring_summary or "```python``` block",
        )

    try:
        assembled = _normalize_authoring_context_result(result.value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Context template returned invalid result shape",
            data={
                "error": str(exc),
                "template_name": template.name,
                "phase": "result_shape",
                "template_pointer": source.docstring_summary or "assemble_context(...) result",
            },
        )
        raise ContextTemplateExecutionError(
            (
                f"Context template '{template.name}' returned invalid context data. "
                "Fix the template or select No template to continue without context management. "
                f"Details: {exc}"
            ),
            template_name=template.name,
            phase="result_shape",
            template_pointer=source.docstring_summary or "assemble_context(...) result",
        ) from exc
    section_name = source.docstring_summary or "Context"
    summary_text = _combined_context_text(assembled.messages)

    logger.set_sinks(["validation"]).info(
        "Context section completed",
        data={
            "event": "context_section_completed",
            "section_name": section_name,
            "section_key": f"authoring:{section_name}",
            "model_alias": "authoring_monty",
            "output_length": len(summary_text),
            "output_hash": None,
            "from_cache": False,
            "cache_scope": None,
            "cache_mode": None,
        },
    )

    if summary_text:
        try:
            upsert_session(session_id=session_id, vault_name=vault_name, metadata=None)
            combined_output = f"## {section_name}\n{summary_text}"
            add_context_summary(
                session_id=session_id,
                vault_name=vault_name,
                turn_index=None,
                template=template,
                model_alias="authoring_monty",
                raw_output=combined_output,
                budget_used=None,
                sections_included=None,
                compiled_prompt=None,
                input_payload={"sections": [section_name]},
            )
            logger.info(
                "Context summary persisted",
                data={
                    "session_id": session_id,
                    "vault_name": vault_name,
                    "template_name": template.name,
                    "sections": [section_name],
                },
            )
            logger.set_sinks(["validation"]).info(
                "Context summary persisted",
                data={
                    "event": "context_summary_persisted",
                    "session_id": session_id,
                    "vault_name": vault_name,
                    "template_name": template.name,
                    "sections": [section_name],
                    "summary_length": len(combined_output),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to persist authoring context summary", data={"error": str(exc)})

    curated_history = []
    curated_history.extend(_context_message_to_model_message(message) for message in assembled.messages)
    if latest_turn_messages:
        if _compiled_history_includes_latest_user(assembled.messages, latest_user_message):
            curated_history.extend(latest_turn_messages[1:])
        else:
            curated_history.extend(latest_turn_messages)
    logger.set_sinks(["validation"]).info(
        "Context history compiled",
        data={
            "event": "context_history_compiled",
            "session_id": session_id,
            "vault_name": vault_name,
            "template_name": template.name,
            "total_messages": len(curated_history),
            "summary_section_count": 1 if summary_text else 0,
            "summary_sections": [section_name] if summary_text else [],
            "latest_user_included": _compiled_history_includes_latest_user(
                assembled.messages,
                latest_user_message,
            ),
        },
    )
    return curated_history


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_context_manager_history_processor(
    *,
    session_id: str,
    vault_name: str,
    vault_path: str,
    model_alias: str,
    template_name: str,
) -> Callable[[RunContext[Any], List[ModelMessage]], Awaitable[List[ModelMessage]]]:
    """
    Factory for a history processor that runs a Monty authoring template and
    injects the assembled context ahead of the recent turns.
    """
    try:
        template = load_template(template_name, Path(vault_path))
        authoring_source = parse_authoring_template_text(template.content)
    except Exception as exc:
        logger.warning(
            "Context template load failed",
            data={
                "error": str(exc),
                "template_name": template_name,
                "phase": "template_load",
                "template_pointer": "Template frontmatter and python block",
            },
        )
        raise ContextTemplateExecutionError(
            (
                f"Context template '{template_name}' could not be loaded. "
                "Fix the template or select No template to continue without context management. "
                f"Details: {exc}"
            ),
            template_name=template_name,
            phase="template_load",
            template_pointer="Template frontmatter and python block",
        ) from exc

    logger.info(
        "Context template loaded",
        data={
            "template_name": template.name,
            "template_source": template.source,
        },
    )
    logger.set_sinks(["validation"]).info(
        "Context template loaded",
        data={
            "event": "context_template_loaded",
            "template_name": template.name,
            "template_source": template.source,
        },
    )

    async def processor(run_context: RunContext[Any], messages: List[ModelMessage]) -> List[ModelMessage]:
        return await _build_authoring_context_history(
            run_context=run_context,
            messages=messages,
            session_id=session_id,
            vault_name=vault_name,
            vault_path=vault_path,
            template=template,
            source=authoring_source,
        )

    return processor
