"""Concrete host adapters for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Any

from core.logger import UnifiedLogger
from core.runtime.buffers import BufferStore
from core.runtime.paths import get_data_root
from core.utils.patterns import PatternUtilities
from core.utils.file_state import WorkflowFileStateManager
from core.workflow.input_resolution import build_input_request, resolve_input_request
from core.workflow.output_resolution import (
    build_output_request,
    normalize_write_mode,
    resolve_header_value,
    resolve_output_request,
    write_resolved_output,
)

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityScope,
    AuthoringExecutionContext,
    AuthoringHost,
    CapabilityNotAllowedError,
    GenerationResult,
    OutputItem,
    OutputResult,
    RetrieveResult,
    RetrievedItem,
)


logger = UnifiedLogger(tag="authoring-host")


def _current_datetime_today() -> datetime:
    """Resolve today's date at runtime so validation can monkey-patch the module clock."""
    return datetime.today()


@dataclass(frozen=True)
class MontyDateTokens:
    """Python-friendly wrapper over the shared date token vocabulary."""

    reference_date: datetime
    week_start_day: int = 0

    def today(self, fmt: str | None = None) -> str:
        return self._resolve("today", fmt)

    def yesterday(self, fmt: str | None = None) -> str:
        return self._resolve("yesterday", fmt)

    def tomorrow(self, fmt: str | None = None) -> str:
        return self._resolve("tomorrow", fmt)

    def this_week(self, fmt: str | None = None) -> str:
        return self._resolve("this-week", fmt)

    def last_week(self, fmt: str | None = None) -> str:
        return self._resolve("last-week", fmt)

    def next_week(self, fmt: str | None = None) -> str:
        return self._resolve("next-week", fmt)

    def this_month(self, fmt: str | None = None) -> str:
        return self._resolve("this-month", fmt)

    def last_month(self, fmt: str | None = None) -> str:
        return self._resolve("last-month", fmt)

    def day_name(self, fmt: str | None = None) -> str:
        return self._resolve("day-name", fmt)

    def month_name(self, fmt: str | None = None) -> str:
        return self._resolve("month-name", fmt)

    def _resolve(self, token: str, fmt: str | None) -> str:
        pattern = token if fmt is None else f"{token}:{fmt}"
        return PatternUtilities.resolve_date_pattern(
            pattern,
            reference_date=self.reference_date,
            week_start_day=self.week_start_day,
        )


@dataclass
class WorkflowAuthoringHost(AuthoringHost):
    """Workflow-scoped host adapter backed by shared workflow runtime services."""

    workflow_id: str
    vault_path: str | None = None
    reference_date: datetime = field(default_factory=_current_datetime_today)
    week_start_day: int = 0
    run_buffers: BufferStore = field(default_factory=BufferStore)
    session_buffers: BufferStore = field(default_factory=BufferStore)
    state_manager: WorkflowFileStateManager | None = None

    def __post_init__(self) -> None:
        if self.vault_path is None:
            if "/" not in self.workflow_id:
                raise ValueError(
                    f"Invalid workflow_id format. Expected 'vault/name', got: {self.workflow_id}"
                )
            vault_name, _workflow_name = self.workflow_id.split("/", 1)
            self.vault_path = os.path.join(str(get_data_root()), vault_name)
        if self.state_manager is None and "/" in self.workflow_id:
            vault_name, _workflow_name = self.workflow_id.split("/", 1)
            self.state_manager = WorkflowFileStateManager(vault_name, self.workflow_id)

    def get_monty_inputs(self) -> dict[str, Any]:
        """Return reserved Monty globals injected by the host."""
        return {
            "date": MontyDateTokens(
                reference_date=self.reference_date,
                week_start_day=self.week_start_day,
            )
        }

    def get_monty_dataclasses(self) -> tuple[type, ...]:
        """Return dataclass types Monty should expose for reserved globals."""
        return (MontyDateTokens,)

    async def handle_retrieve(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> RetrieveResult:
        request_type, ref, options = _parse_retrieve_call(call)
        if request_type != "file":
            raise ValueError(
                f"Unsupported retrieve type '{request_type}'. Only 'file' is implemented in the MVP."
            )

        _ensure_file_ref_allowed(ref=ref, scope=context.scope)
        parameters = _build_file_parameters(options)

        logger.info(
            "authoring_retrieve_allowed",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "options": parameters,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_retrieve_allowed",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "options": parameters,
            },
        )

        resolved = resolve_input_request(
            build_input_request(target_type="file", target=ref, parameters=parameters),
            vault_path=self.vault_path or "",
            reference_date=self.reference_date,
            week_start_day=self.week_start_day,
            state_manager=self.state_manager,
            buffer_store=self.run_buffers,
            buffer_store_registry={
                "run": self.run_buffers,
                "session": self.session_buffers,
            },
        )
        items = [_normalize_file_record(record) for record in resolved]
        logger.info(
            "authoring_retrieve_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "item_count": len(items),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_retrieve_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "item_count": len(items),
            },
        )
        return RetrieveResult(
            type=request_type,
            ref=ref,
            items=tuple(items),
        )

    async def handle_output(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> OutputResult:
        request_type, ref, data, options = _parse_output_call(call)
        if request_type != "file":
            raise ValueError(
                f"Unsupported output type '{request_type}'. Only 'file' is implemented in the MVP."
            )

        _ensure_file_output_allowed(ref=ref, scope=context.scope)
        write_mode, header = _build_file_output_options(options, reference_date=self.reference_date, week_start_day=self.week_start_day)
        resolved_target = resolve_output_request(
            build_output_request(target_type="file", target=ref, parameters={}),
            vault_path=self.vault_path or "",
            reference_date=self.reference_date,
            week_start_day=self.week_start_day,
        )

        logger.info(
            "authoring_output_allowed",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "write_mode": write_mode,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_output_allowed",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "write_mode": write_mode,
            },
        )
        write_result = write_resolved_output(
            resolved_target=resolved_target,
            content=_coerce_output_data(data),
            write_mode=write_mode,
            vault_path=self.vault_path,
            buffer_store=self.run_buffers,
            buffer_store_registry={
                "run": self.run_buffers,
                "session": self.session_buffers,
            },
            header=header,
            metadata={
                "source": "authoring_monty",
                "origin_id": context.workflow_id,
                "origin_type": "authoring_template",
            },
            default_scope="run",
        )
        resolved_ref = _normalize_output_ref(
            str(write_result.get("path") or resolved_target.path or ref),
            vault_path=self.vault_path or "",
        )
        logger.info(
            "authoring_output_written",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "resolved_ref": resolved_ref,
                "write_mode": write_mode,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_output_written",
            data={
                "workflow_id": context.workflow_id,
                "type": request_type,
                "ref": ref,
                "resolved_ref": resolved_ref,
                "write_mode": write_mode,
            },
        )
        return OutputResult(
            type=request_type,
            ref=ref,
            status="written",
            item=OutputItem(
                ref=ref,
                resolved_ref=resolved_ref,
                mode=write_mode or "append",
            ),
        )

    async def handle_generate(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> GenerationResult:
        from core.directives.model import ModelDirective
        from core.llm.agents import create_agent, generate_response
        from core.llm.model_selection import ModelExecutionSpec

        prompt, instructions, model_value, options = _parse_generate_call(call)
        resolved_model_value = _apply_generate_options_to_model(model_value, options)

        model = None
        if resolved_model_value:
            model = ModelDirective().process_value(resolved_model_value, self.vault_path or "")
            if isinstance(model, ModelExecutionSpec) and model.mode == "skip":
                raise ValueError("generate does not support skip model mode")

        logger.info(
            "authoring_generate_started",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "instructions_present": bool(instructions),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_generate_started",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "instructions_present": bool(instructions),
            },
        )
        agent = await create_agent(model=model)
        if instructions:
            agent.instructions(lambda _ctx, text=instructions: text)
        output = await generate_response(agent, prompt)
        text = _coerce_output_data(output)
        logger.info(
            "authoring_generate_completed",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "output_chars": len(text),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_generate_completed",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "output_chars": len(text),
            },
        )
        return GenerationResult(
            status="generated",
            model=resolved_model_value or "default",
            output=text,
        )

    async def handle_call_tool(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any:
        raise NotImplementedError("call_tool is not implemented for the Monty MVP host")

    async def handle_import_content(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any:
        raise NotImplementedError("import_content is not implemented for the Monty MVP host")


def _parse_retrieve_call(call: AuthoringCapabilityCall) -> tuple[str, str, dict[str, Any]]:
    if call.args:
        raise ValueError("retrieve only supports keyword arguments")
    request_type = str(call.kwargs.get("type") or "").strip().lower()
    ref = str(call.kwargs.get("ref") or "").strip()
    raw_options = call.kwargs.get("options")
    if not request_type:
        raise ValueError("retrieve requires a non-empty 'type'")
    if not ref:
        raise ValueError("retrieve requires a non-empty 'ref'")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("retrieve options must be a dictionary when provided")
    return request_type, ref, options


def _ensure_file_ref_allowed(*, ref: str, scope: AuthoringCapabilityScope) -> None:
    if os.path.isabs(ref):
        raise CapabilityNotAllowedError("retrieve file refs must be vault-relative paths")
    normalized_candidates = {ref.strip()}
    if "." not in os.path.basename(ref):
        normalized_candidates.add(f"{ref}.md")
    allowed_patterns = tuple(path.strip() for path in scope.readable_paths if path.strip())
    if not allowed_patterns:
        return
    if any(
        fnmatchcase(candidate, pattern)
        for candidate in normalized_candidates
        for pattern in allowed_patterns
    ):
        return
    raise CapabilityNotAllowedError(f"File ref '{ref}' is outside the configured read scope")


def _ensure_file_output_allowed(*, ref: str, scope: AuthoringCapabilityScope) -> None:
    if os.path.isabs(ref):
        raise CapabilityNotAllowedError("output file refs must be vault-relative paths")
    normalized_candidates = {ref.strip()}
    if "." not in os.path.basename(ref):
        normalized_candidates.add(f"{ref}.md")
    allowed_patterns = tuple(path.strip() for path in scope.writable_paths if path.strip())
    if not allowed_patterns:
        return
    if any(
        fnmatchcase(candidate, pattern)
        for candidate in normalized_candidates
        for pattern in allowed_patterns
    ):
        return
    raise CapabilityNotAllowedError(f"File ref '{ref}' is outside the configured write scope")


def _build_file_parameters(options: dict[str, Any]) -> dict[str, Any]:
    supported_keys = {
        "required",
        "refs_only",
        "pending",
        "latest",
        "limit",
        "order",
        "dir",
        "dt_pattern",
        "dt_format",
    }
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported retrieve(file) options: {', '.join(unknown)}")

    parameters: dict[str, Any] = {}
    for key in ("required", "refs_only", "latest", "limit", "order", "dir", "dt_pattern", "dt_format"):
        if key in options:
            parameters[key] = options[key]

    pending = options.get("pending")
    if pending is None:
        return parameters
    if isinstance(pending, bool):
        parameters["pending"] = pending
        return parameters
    normalized = str(pending).strip().lower()
    if normalized == "include":
        return parameters
    if normalized == "only":
        parameters["pending"] = True
        return parameters
    raise ValueError("retrieve(file) option 'pending' must be true/false or one of: include, only")


def _parse_output_call(call: AuthoringCapabilityCall) -> tuple[str, str, Any, dict[str, Any]]:
    if call.args:
        raise ValueError("output only supports keyword arguments")
    request_type = str(call.kwargs.get("type") or "").strip().lower()
    ref = str(call.kwargs.get("ref") or "").strip()
    if not request_type:
        raise ValueError("output requires a non-empty 'type'")
    if not ref:
        raise ValueError("output requires a non-empty 'ref'")
    if "data" not in call.kwargs:
        raise ValueError("output requires 'data'")
    raw_options = call.kwargs.get("options")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("output options must be a dictionary when provided")
    return request_type, ref, call.kwargs["data"], options


def _parse_generate_call(call: AuthoringCapabilityCall) -> tuple[str, str | None, str | None, dict[str, Any]]:
    if call.args:
        raise ValueError("generate only supports keyword arguments")
    prompt = str(call.kwargs.get("prompt") or "")
    if not prompt.strip():
        raise ValueError("generate requires a non-empty 'prompt'")
    raw_instructions = call.kwargs.get("instructions")
    instructions = None if raw_instructions is None else str(raw_instructions).strip() or None
    raw_model = call.kwargs.get("model")
    model_value = None if raw_model is None else str(raw_model).strip() or None
    raw_options = call.kwargs.get("options")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("generate options must be a dictionary when provided")
    return prompt, instructions, model_value, options


def _apply_generate_options_to_model(model_value: str | None, options: dict[str, Any]) -> str | None:
    supported_keys = {"thinking"}
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported generate options: {', '.join(unknown)}")
    if "thinking" not in options:
        return model_value
    thinking_value = options["thinking"]
    if not isinstance(thinking_value, bool):
        raise ValueError("generate option 'thinking' must be true or false")
    if model_value is None:
        raise ValueError("generate option 'thinking' currently requires an explicit model")
    return f"{model_value} (thinking={'true' if thinking_value else 'false'})"


def _build_file_output_options(
    options: dict[str, Any],
    *,
    reference_date: datetime,
    week_start_day: int,
) -> tuple[str, str | None]:
    supported_keys = {"mode", "header"}
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported output(file) options: {', '.join(unknown)}")
    raw_mode = str(options.get("mode") or "append").strip().lower()
    write_mode = normalize_write_mode(raw_mode)
    if write_mode is None:
        write_mode = "append"
    raw_header = options.get("header")
    header: str | None = None
    if raw_header is not None:
        text = str(raw_header).strip()
        if text:
            header = resolve_header_value(
                text,
                reference_date=reference_date,
                week_start_day=week_start_day,
            )
    return write_mode, header


def _coerce_output_data(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_output_ref(path: str, *, vault_path: str) -> str:
    if not path or not vault_path:
        return path
    try:
        normalized_vault = os.path.realpath(vault_path)
        normalized_path = os.path.realpath(path)
        if normalized_path.startswith(normalized_vault + os.sep):
            return os.path.relpath(normalized_path, normalized_vault).replace("\\", "/")
    except Exception:
        return path
    return path


def _normalize_file_record(record: dict[str, Any]) -> RetrievedItem:
    if record.get("_workflow_signal") == "skip_step":
        return RetrievedItem(
            ref=None,
            content="",
            exists=False,
            metadata={
                "signal": "skip_step",
                "reason": record.get("reason"),
            },
        )

    source_ref = record.get("source_path") or record.get("filepath") or ""
    exists = bool(record.get("found", True))
    metadata = {
        "filename": record.get("filename"),
        "error": record.get("error"),
    }
    if record.get("filepath") is not None:
        metadata["filepath"] = record.get("filepath")
    if record.get("source_path") is not None:
        metadata["source_path"] = record.get("source_path")
    return RetrievedItem(
        ref=source_ref,
        content=record.get("content", ""),
        exists=exists,
        metadata=metadata,
    )
