"""Concrete host adapters for the experimental Monty-backed authoring runtime."""

from __future__ import annotations

import os
import inspect
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from types import SimpleNamespace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from core.logger import UnifiedLogger
from core.runtime.buffers import BufferStore
from core.runtime.paths import get_data_root
from core.context.cache_semantics import parse_cache_mode_value
from core.context.manager_helpers import extract_role_and_text, run_slice
from core.context.store import (
    get_cache_artifact,
    purge_expired_cache_artifacts,
    upsert_cache_artifact,
)
from core.utils.patterns import PatternUtilities
from core.utils.file_state import WorkflowFileStateManager
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.authoring.shared.execution_prep import build_step_prompt, resolve_step_model_execution
from core.authoring.shared.input_resolution import build_input_request, resolve_input_request
from core.authoring.shared.markdown_parse import parse_markdown_content
from core.authoring.shared.output_resolution import (
    build_output_request,
    normalize_write_mode,
    resolve_output_request,
    write_resolved_output,
)

from core.authoring.contracts import (
    AssembleContextResult,
    AuthoringCapabilityCall,
    AuthoringCapabilityScope,
    AuthoringExecutionContext,
    AuthoringHost,
    AuthoringFinishSignal,
    CallToolResult,
    CapabilityNotAllowedError,
    ContextMessage,
    FinishResult,
    GenerationResult,
    MarkdownCodeBlock,
    MarkdownHeading,
    MarkdownImage,
    MarkdownSection,
    OutputItem,
    OutputResult,
    ParsedMarkdown,
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
    session_key: str | None = None
    chat_session_id: str | None = None
    message_history: list[ModelMessage] | None = None

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
        if self.session_key is None:
            self.session_key = self.workflow_id
        if self.chat_session_id is None:
            self.chat_session_id = self.session_key

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
        return (
            MontyDateTokens,
            MarkdownHeading,
            MarkdownSection,
            MarkdownCodeBlock,
            MarkdownImage,
            ParsedMarkdown,
        )

    async def handle_retrieve(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> RetrieveResult:
        request_type, ref, options = _parse_retrieve_call(call)
        if request_type == "cache":
            return self._handle_cache_retrieve(ref=ref, options=options, context=context)
        if request_type == "run":
            return self._handle_run_retrieve(ref=ref, options=options, context=context)
        if request_type != "file":
            raise ValueError(
                f"Unsupported retrieve type '{request_type}'. Supported types are: file, cache, run."
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
        if request_type == "cache":
            return self._handle_cache_output(ref=ref, data=data, options=options, context=context)
        if request_type != "file":
            raise ValueError(
                f"Unsupported output type '{request_type}'. Supported types are: file, cache."
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

        prompt, inputs, instructions, model_value, tool_names, cache_policy, options = _parse_generate_call(call)
        resolved_model_value = _apply_generate_options_to_model(model_value, options)
        if tool_names:
            _ensure_generate_tools_allowed(tool_names=tool_names, scope=context.scope)
        prompt_input: Any = prompt
        attached_image_count = 0
        input_warnings: list[str] = []
        if inputs:
            model_execution = resolve_step_model_execution(resolved_model_value)
            prompt_input, _prompt_text, attached_image_count, input_warnings = build_step_prompt(
                base_prompt=prompt,
                input_file_data=_build_generate_input_file_data(inputs),
                vault_path=self.vault_path or "",
                model_execution=model_execution,
            )
        cache_mode: str | None = None
        cache_ttl_seconds: int | None = None
        cache_ref: str | None = None
        if cache_policy is not None:
            cache_mode, cache_ttl_seconds = _parse_generate_cache_policy(cache_policy)
            cache_ref = _build_generate_cache_ref(
                prompt=prompt,
                inputs=inputs,
                instructions=instructions,
                model_value=resolved_model_value or "default",
                tool_names=tool_names,
                cache_mode=cache_mode,
                ttl_seconds=cache_ttl_seconds,
            )
            purge_expired_cache_artifacts(now=self.reference_date)
            cached = get_cache_artifact(
                owner_id=context.workflow_id,
                session_key=self.session_key,
                artifact_ref=cache_ref,
                now=self.reference_date,
                week_start_day=self.week_start_day,
            )
            if cached is not None:
                logger.info(
                    "authoring_generate_cache_hit",
                    data={
                        "workflow_id": context.workflow_id,
                        "model": resolved_model_value or "default",
                        "cache_mode": cache_mode,
                        "cache_ref": cache_ref,
                        "output_chars": len(cached["raw_content"]),
                    },
                )
                logger.set_sinks(["validation"]).info(
                    "authoring_generate_cache_hit",
                    data={
                        "workflow_id": context.workflow_id,
                        "model": resolved_model_value or "default",
                        "cache_mode": cache_mode,
                        "cache_ref": cache_ref,
                        "output_chars": len(cached["raw_content"]),
                    },
                )
                return GenerationResult(
                    status="cached",
                    model=resolved_model_value or "default",
                    output=cached["raw_content"],
                )

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
                "input_count": len(inputs),
                "attached_image_count": attached_image_count,
                "input_warnings": input_warnings,
                "tool_names": list(tool_names),
                "cache_mode": cache_mode,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_generate_started",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "instructions_present": bool(instructions),
                "input_count": len(inputs),
                "attached_image_count": attached_image_count,
                "input_warnings": input_warnings,
                "tool_names": list(tool_names),
                "cache_mode": cache_mode,
            },
        )
        bound_tools = None
        if tool_names:
            binding = resolve_tool_binding(
                list(tool_names),
                vault_path=self.vault_path or "",
                week_start_day=self.week_start_day,
            )
            bound_tools = binding.tool_functions
        agent = await create_agent(model=model, tools=bound_tools)
        if instructions:
            agent.instructions(lambda _ctx, text=instructions: text)
        output = await generate_response(agent, prompt_input)
        text = _coerce_output_data(output)
        if cache_mode is not None and cache_ref is not None:
            upsert_cache_artifact(
                owner_id=context.workflow_id,
                session_key=self.session_key,
                artifact_ref=cache_ref,
                cache_mode=cache_mode,
                ttl_seconds=cache_ttl_seconds,
                raw_content=text,
                metadata={
                    "kind": "generate",
                    "model": resolved_model_value or "default",
                    "prompt_chars": len(prompt),
                    "instructions_present": bool(instructions),
                    "tool_names": list(tool_names),
                },
                origin="authoring_generate",
                now=self.reference_date,
                week_start_day=self.week_start_day,
            )
            logger.info(
                "authoring_generate_cache_stored",
                data={
                    "workflow_id": context.workflow_id,
                    "model": resolved_model_value or "default",
                    "tool_names": list(tool_names),
                    "cache_mode": cache_mode,
                    "cache_ref": cache_ref,
                    "output_chars": len(text),
                },
            )
            logger.set_sinks(["validation"]).info(
                "authoring_generate_cache_stored",
                data={
                    "workflow_id": context.workflow_id,
                    "model": resolved_model_value or "default",
                    "tool_names": list(tool_names),
                    "cache_mode": cache_mode,
                    "cache_ref": cache_ref,
                    "output_chars": len(text),
                },
            )
        logger.info(
            "authoring_generate_completed",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "tool_names": list(tool_names),
                "output_chars": len(text),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_generate_completed",
            data={
                "workflow_id": context.workflow_id,
                "model": resolved_model_value or "default",
                "tool_names": list(tool_names),
                "output_chars": len(text),
            },
        )
        return GenerationResult(
            status="generated",
            model=resolved_model_value or "default",
            output=text,
        )

    async def handle_parse_markdown(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> ParsedMarkdown:
        source = _parse_markdown_source(call)
        logger.info(
            "authoring_parse_markdown_started",
            data={
                "workflow_id": context.workflow_id,
                "source_type": type(source).__name__,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_parse_markdown_started",
            data={
                "workflow_id": context.workflow_id,
                "source_type": type(source).__name__,
            },
        )
        parsed = parse_markdown_content(source)
        logger.info(
            "authoring_parse_markdown_completed",
            data={
                "workflow_id": context.workflow_id,
                "heading_count": len(parsed.headings),
                "section_count": len(parsed.sections),
                "code_block_count": len(parsed.code_blocks),
                "image_count": len(parsed.images),
                "frontmatter_keys": sorted(parsed.frontmatter),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_parse_markdown_completed",
            data={
                "workflow_id": context.workflow_id,
                "heading_count": len(parsed.headings),
                "section_count": len(parsed.sections),
                "code_block_count": len(parsed.code_blocks),
                "image_count": len(parsed.images),
                "frontmatter_keys": sorted(parsed.frontmatter),
            },
        )
        return parsed

    async def handle_call_tool(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> CallToolResult:
        tool_name, arguments, options = _parse_call_tool_call(call)
        _ensure_tool_allowed(tool_name=tool_name, scope=context.scope)

        logger.info(
            "authoring_call_tool_started",
            data={
                "workflow_id": context.workflow_id,
                "tool": tool_name,
                "argument_keys": sorted(arguments.keys()),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_call_tool_started",
            data={
                "workflow_id": context.workflow_id,
                "tool": tool_name,
                "argument_keys": sorted(arguments.keys()),
            },
        )

        binding = resolve_tool_binding(
            [tool_name],
            vault_path=self.vault_path or "",
            week_start_day=self.week_start_day,
        )
        tool_spec = next((spec for spec in binding.tool_specs if spec.name == tool_name), None)
        if tool_spec is None:
            raise ValueError(f"Resolved tool '{tool_name}' is unavailable in the current host context")

        result = await _invoke_bound_tool(
            tool_spec.tool_function,
            tool_name=tool_name,
            arguments=arguments,
            run_buffers=self.run_buffers,
            session_buffers=self.session_buffers,
        )
        output, metadata = _normalize_tool_result(result)

        logger.info(
            "authoring_call_tool_completed",
            data={
                "workflow_id": context.workflow_id,
                "tool": tool_name,
                "output_chars": len(output),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_call_tool_completed",
            data={
                "workflow_id": context.workflow_id,
                "tool": tool_name,
                "output_chars": len(output),
            },
        )

        return CallToolResult(
            name=tool_name,
            status="completed",
            output=output,
            metadata=metadata,
        )

    async def handle_assemble_context(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> AssembleContextResult:
        history, context_messages, instructions, latest_user_message = _parse_assemble_context_call(call)
        assembled_messages: list[ContextMessage] = []

        if instructions:
            assembled_messages.append(ContextMessage(role="system", content=instructions))
        for item in context_messages:
            assembled_messages.append(_normalize_context_message(item, default_role="system"))
        for item in history:
            assembled_messages.append(_normalize_context_message(item))
        if latest_user_message is not None:
            assembled_messages.append(_normalize_context_message(latest_user_message, default_role="user"))

        logger.info(
            "authoring_assemble_context_completed",
            data={
                "workflow_id": context.workflow_id,
                "message_count": len(assembled_messages),
                "instruction_count": 1 if instructions else 0,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_assemble_context_completed",
            data={
                "workflow_id": context.workflow_id,
                "message_count": len(assembled_messages),
                "instruction_count": 1 if instructions else 0,
            },
        )

        return AssembleContextResult(
            messages=tuple(assembled_messages),
            instructions=(instructions,) if instructions else (),
        )

    async def handle_import_content(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> Any:
        raise NotImplementedError("import_content is not implemented for the Monty MVP host")

    async def handle_finish(
        self,
        call: AuthoringCapabilityCall,
        context: AuthoringExecutionContext,
    ) -> FinishResult:
        status, reason = _parse_finish_call(call)
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

    def _handle_cache_retrieve(
        self,
        *,
        ref: str,
        options: dict[str, Any],
        context: AuthoringExecutionContext,
    ) -> RetrieveResult:
        _ensure_cache_ref_allowed(ref=ref, scope=context.scope)
        _ensure_cache_retrieve_options_supported(options)
        purge_expired_cache_artifacts(now=self.reference_date)
        artifact = get_cache_artifact(
            owner_id=context.workflow_id,
            session_key=self.session_key,
            artifact_ref=ref,
            now=self.reference_date,
            week_start_day=self.week_start_day,
        )
        item = _normalize_cache_record(ref=ref, record=artifact)
        logger.info(
            "authoring_retrieve_cache_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": "cache",
                "ref": ref,
                "exists": item.exists,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_retrieve_cache_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": "cache",
                "ref": ref,
                "exists": item.exists,
            },
        )
        return RetrieveResult(type="cache", ref=ref, items=(item,))

    def _handle_run_retrieve(
        self,
        *,
        ref: str,
        options: dict[str, Any],
        context: AuthoringExecutionContext,
    ) -> RetrieveResult:
        if ref != "session":
            raise ValueError("retrieve(run) currently supports only ref='session'")
        if self.message_history is None:
            raise ValueError("retrieve(run) requires chat session history in the host context")

        limit = _parse_history_limit(options, default="all")
        if limit == "all":
            selected_messages = list(self.message_history)
        else:
            selected_messages = run_slice(list(self.message_history), limit)

        items = tuple(_normalize_run_message(message) for message in selected_messages)
        logger.info(
            "authoring_retrieve_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": "run",
                "ref": ref,
                "item_count": len(items),
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_retrieve_resolved",
            data={
                "workflow_id": context.workflow_id,
                "type": "run",
                "ref": ref,
                "item_count": len(items),
            },
        )
        return RetrieveResult(type="run", ref=ref, items=items)

    def _handle_cache_output(
        self,
        *,
        ref: str,
        data: Any,
        options: dict[str, Any],
        context: AuthoringExecutionContext,
    ) -> OutputResult:
        _ensure_cache_output_allowed(ref=ref, scope=context.scope)
        write_mode, cache_mode, ttl_seconds = _build_cache_output_options(options)
        purge_expired_cache_artifacts(now=self.reference_date)

        content = _coerce_output_data(data)
        if write_mode == "append":
            existing = get_cache_artifact(
                owner_id=context.workflow_id,
                session_key=self.session_key,
                artifact_ref=ref,
                now=self.reference_date,
                week_start_day=self.week_start_day,
            )
            if existing is not None:
                content = f"{existing['raw_content']}{content}"

        upsert_cache_artifact(
            owner_id=context.workflow_id,
            session_key=self.session_key,
            artifact_ref=ref,
            cache_mode=cache_mode,
            ttl_seconds=ttl_seconds,
            raw_content=content,
            metadata={
                "type": "cache",
                "write_mode": write_mode,
                "workflow_id": context.workflow_id,
            },
            origin="authoring_monty",
            now=self.reference_date,
            week_start_day=self.week_start_day,
        )
        logger.info(
            "authoring_output_cache_written",
            data={
                "workflow_id": context.workflow_id,
                "type": "cache",
                "ref": ref,
                "write_mode": write_mode,
                "cache_mode": cache_mode,
                "ttl_seconds": ttl_seconds,
            },
        )
        logger.set_sinks(["validation"]).info(
            "authoring_output_cache_written",
            data={
                "workflow_id": context.workflow_id,
                "type": "cache",
                "ref": ref,
                "write_mode": write_mode,
                "cache_mode": cache_mode,
                "ttl_seconds": ttl_seconds,
            },
        )
        return OutputResult(
            type="cache",
            ref=ref,
            status="written",
            item=OutputItem(ref=ref, resolved_ref=ref, mode=write_mode),
        )


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
        raise CapabilityNotAllowedError(
            "retrieve(file) requires explicit authoring.retrieve.file frontmatter entries"
        )
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
        raise CapabilityNotAllowedError(
            "output(file) requires explicit authoring.output.file frontmatter entries"
        )
    if any(
        fnmatchcase(candidate, pattern)
        for candidate in normalized_candidates
        for pattern in allowed_patterns
    ):
        return
    raise CapabilityNotAllowedError(f"File ref '{ref}' is outside the configured write scope")


def _ensure_cache_ref_allowed(*, ref: str, scope: AuthoringCapabilityScope) -> None:
    allowed_patterns = tuple(pattern.strip() for pattern in scope.readable_cache_refs if pattern.strip())
    if not allowed_patterns:
        raise CapabilityNotAllowedError(
            "retrieve(cache) requires explicit authoring.retrieve.cache frontmatter entries"
        )
    if any(fnmatchcase(ref, pattern) for pattern in allowed_patterns):
        return
    raise CapabilityNotAllowedError(f"Cache ref '{ref}' is outside the configured read scope")


def _ensure_cache_output_allowed(*, ref: str, scope: AuthoringCapabilityScope) -> None:
    allowed_patterns = tuple(pattern.strip() for pattern in scope.writable_cache_refs if pattern.strip())
    if not allowed_patterns:
        raise CapabilityNotAllowedError(
            "output(cache) requires explicit authoring.output.cache frontmatter entries"
        )
    if any(fnmatchcase(ref, pattern) for pattern in allowed_patterns):
        return
    raise CapabilityNotAllowedError(f"Cache ref '{ref}' is outside the configured write scope")


def _ensure_cache_retrieve_options_supported(options: dict[str, Any]) -> None:
    if options:
        unknown = ", ".join(sorted(options))
        raise ValueError(f"Unsupported retrieve(cache) options: {unknown}")


def _build_file_parameters(options: dict[str, Any]) -> dict[str, Any]:
    supported_keys = {
        "refs_only",
        "pending",
    }
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported retrieve(file) options: {', '.join(unknown)}")

    parameters: dict[str, Any] = {}
    for key in ("refs_only",):
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


def _parse_generate_call(
    call: AuthoringCapabilityCall,
) -> tuple[
    str,
    tuple[RetrievedItem, ...],
    str | None,
    str | None,
    tuple[str, ...],
    str | dict[str, Any] | None,
    dict[str, Any],
]:
    if call.args:
        raise ValueError("generate only supports keyword arguments")
    prompt = str(call.kwargs.get("prompt") or "")
    if not prompt.strip():
        raise ValueError("generate requires a non-empty 'prompt'")
    raw_inputs = call.kwargs.get("inputs")
    inputs = _normalize_generate_inputs(raw_inputs)
    raw_instructions = call.kwargs.get("instructions")
    instructions = None if raw_instructions is None else str(raw_instructions).strip() or None
    raw_model = call.kwargs.get("model")
    model_value = None if raw_model is None else str(raw_model).strip() or None
    raw_tools = call.kwargs.get("tools")
    if raw_tools is None:
        tool_names: tuple[str, ...] = ()
    elif isinstance(raw_tools, (list, tuple)):
        normalized_tools: list[str] = []
        for item in raw_tools:
            if not isinstance(item, str):
                raise ValueError("generate tools entries must be strings")
            normalized = item.strip()
            if normalized:
                normalized_tools.append(normalized)
        tool_names = tuple(normalized_tools)
    else:
        raise ValueError("generate tools must be a list or tuple of strings when provided")
    raw_cache = call.kwargs.get("cache")
    cache_value: str | dict[str, Any] | None
    if raw_cache is None:
        cache_value = None
    elif isinstance(raw_cache, str):
        cache_value = raw_cache.strip()
    elif isinstance(raw_cache, dict):
        cache_value = dict(raw_cache)
    else:
        raise ValueError("generate cache must be a string or dictionary when provided")
    raw_options = call.kwargs.get("options")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("generate options must be a dictionary when provided")
    return prompt, inputs, instructions, model_value, tool_names, cache_value, options


def _normalize_generate_inputs(value: Any) -> tuple[RetrievedItem, ...]:
    if value is None:
        return ()
    if isinstance(value, RetrieveResult):
        return tuple(value.items)
    if isinstance(value, RetrievedItem):
        return (value,)
    if isinstance(value, (list, tuple)):
        items: list[RetrievedItem] = []
        for item in value:
            if not isinstance(item, RetrievedItem):
                raise ValueError("generate inputs entries must be RetrievedItem values")
            items.append(item)
        return tuple(items)
    raise ValueError("generate inputs must be a RetrieveResult, RetrievedItem, list, or tuple when provided")


def _parse_generate_cache_policy(cache_value: str | dict[str, Any]) -> tuple[str, int | None]:
    if isinstance(cache_value, str):
        normalized = cache_value.strip()
        if not normalized:
            raise ValueError("generate cache cannot be empty when provided")
        parsed = parse_cache_mode_value(normalized)
        return str(parsed["mode"]), parsed.get("ttl_seconds")

    unknown = sorted(set(cache_value) - {"mode"})
    if unknown:
        raise ValueError(f"Unsupported generate cache options: {', '.join(unknown)}")
    raw_mode = str(cache_value.get("mode") or "").strip()
    if not raw_mode:
        raise ValueError("generate cache object requires a non-empty 'mode'")
    parsed = parse_cache_mode_value(raw_mode)
    return str(parsed["mode"]), parsed.get("ttl_seconds")


def _build_generate_cache_ref(
    *,
    prompt: str,
    inputs: tuple[RetrievedItem, ...],
    instructions: str | None,
    model_value: str,
    tool_names: tuple[str, ...],
    cache_mode: str,
    ttl_seconds: int | None,
) -> str:
    cache_key_payload = {
        "kind": "generate",
        "model": model_value,
        "prompt": prompt,
        "inputs": [
            {
                "ref": item.ref,
                "content": item.content,
                "exists": item.exists,
                "metadata": item.metadata,
            }
            for item in inputs
        ],
        "instructions": instructions or "",
        "tools": list(tool_names),
        "cache_mode": cache_mode,
        "ttl_seconds": ttl_seconds,
    }
    digest = hashlib.sha256(
        json.dumps(cache_key_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"generate/{digest}"


def _parse_call_tool_call(call: AuthoringCapabilityCall) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if call.args:
        raise ValueError("call_tool only supports keyword arguments")
    tool_name = str(call.kwargs.get("name") or "").strip()
    if not tool_name:
        raise ValueError("call_tool requires a non-empty 'name'")
    raw_arguments = call.kwargs.get("arguments")
    if raw_arguments is None:
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, dict):
        arguments = dict(raw_arguments)
    else:
        raise ValueError("call_tool arguments must be a dictionary when provided")
    raw_options = call.kwargs.get("options")
    if raw_options is None:
        options: dict[str, Any] = {}
    elif isinstance(raw_options, dict):
        options = dict(raw_options)
    else:
        raise ValueError("call_tool options must be a dictionary when provided")
    if options:
        raise ValueError("call_tool options are reserved for future use and must currently be omitted")
    return tool_name, arguments, options


def _parse_finish_call(call: AuthoringCapabilityCall) -> tuple[str, str]:
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


def _parse_markdown_source(call: AuthoringCapabilityCall) -> str:
    if call.args:
        raise ValueError("parse_markdown only supports keyword arguments")
    unknown = sorted(set(call.kwargs) - {"value"})
    if unknown:
        raise ValueError(f"Unsupported parse_markdown arguments: {', '.join(unknown)}")
    value = call.kwargs.get("value")
    if isinstance(value, RetrievedItem):
        return value.content
    if isinstance(value, str):
        return value
    raise ValueError("parse_markdown value must be a RetrievedItem or string")


def _parse_assemble_context_call(
    call: AuthoringCapabilityCall,
) -> tuple[tuple[Any, ...], tuple[Any, ...], str | None, Any | None]:
    if call.args:
        raise ValueError("assemble_context only supports keyword arguments")

    history = _normalize_object_sequence(call.kwargs.get("history"))
    context_messages = _normalize_object_sequence(call.kwargs.get("context_messages"))
    instructions = _normalize_optional_string(call.kwargs.get("instructions"))
    latest_user_message = call.kwargs.get("latest_user_message")
    return history, context_messages, instructions, latest_user_message


def _ensure_tool_allowed(*, tool_name: str, scope: AuthoringCapabilityScope) -> None:
    allowed_tools = tuple(name.strip() for name in scope.allowed_tools if name.strip())
    if not allowed_tools:
        raise CapabilityNotAllowedError(
            "call_tool requires explicit authoring.tools frontmatter entries for allowed tool names"
        )
    if tool_name not in allowed_tools:
        raise CapabilityNotAllowedError(f"Tool '{tool_name}' is outside the configured tool scope")


def _ensure_generate_tools_allowed(*, tool_names: tuple[str, ...], scope: AuthoringCapabilityScope) -> None:
    allowed_tools = tuple(name.strip() for name in scope.allowed_tools if name.strip())
    if not allowed_tools:
        raise CapabilityNotAllowedError(
            "generate(..., tools=[...]) requires explicit authoring.tools frontmatter entries"
        )
    for tool_name in tool_names:
        if tool_name not in allowed_tools:
            raise CapabilityNotAllowedError(
                f"Tool '{tool_name}' is outside the configured tool scope"
            )


def _parse_history_limit(options: dict[str, Any], *, default: int | str) -> int | str:
    unknown = sorted(set(options) - {"limit"})
    if unknown:
        raise ValueError(f"Unsupported options: {', '.join(unknown)}")
    raw_limit = options.get("limit", default)
    if isinstance(raw_limit, str):
        normalized = raw_limit.strip().lower()
        if normalized == "all":
            return "all"
        if normalized.isdigit():
            parsed = int(normalized)
            if parsed <= 0:
                raise ValueError("limit must be a positive integer or 'all'")
            return parsed
        raise ValueError("limit must be a positive integer or 'all'")
    if isinstance(raw_limit, int):
        if raw_limit <= 0:
            raise ValueError("limit must be a positive integer or 'all'")
        return raw_limit
    raise ValueError("limit must be a positive integer or 'all'")


def _normalize_run_message(message: ModelMessage) -> RetrievedItem:
    role, content = extract_role_and_text(message)
    run_id = getattr(message, "run_id", None)
    return RetrievedItem(
        ref=run_id or role,
        content=content,
        exists=True,
        metadata={
            "role": role,
            "run_id": run_id,
            "message_type": type(message).__name__,
        },
    )


def _normalize_object_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise ValueError("assemble_context sequences must be lists or tuples when provided")


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("assemble_context instructions must be a string when provided")
    normalized = value.strip()
    return normalized or None


def _build_generate_input_file_data(inputs: tuple[RetrievedItem, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in inputs:
        metadata = dict(item.metadata or {})
        source_path = str(metadata.get("source_path") or item.ref or "").strip()
        filepath = str(metadata.get("filepath") or "").strip()
        if not filepath and source_path:
            filepath = source_path[:-3] if source_path.endswith(".md") else source_path
        if not source_path and item.ref:
            source_path = str(item.ref)
        if not source_path:
            raise ValueError("generate inputs must come from retrieve(file) results with source paths")

        records.append(
            {
                "filepath": filepath or source_path,
                "source_path": source_path,
                "filename": metadata.get("filename"),
                "content": item.content,
                "found": item.exists,
                "error": metadata.get("error"),
                "refs_only": bool(metadata.get("refs_only")),
            }
        )
    return records


def _normalize_context_message(value: Any, *, default_role: str | None = None) -> ContextMessage:
    if isinstance(value, ContextMessage):
        return value
    if isinstance(value, RetrievedItem):
        role = str(value.metadata.get("role") or default_role or "system").strip().lower()
        return ContextMessage(role=role, content=value.content, metadata=dict(value.metadata))
    if isinstance(value, dict):
        role = str(value.get("role") or default_role or "system").strip().lower()
        content = str(value.get("content") or "")
        metadata = value.get("metadata")
        if metadata is None:
            metadata_dict: dict[str, Any] = {}
        elif isinstance(metadata, dict):
            metadata_dict = dict(metadata)
        else:
            raise ValueError("assemble_context message metadata must be a dictionary when provided")
        return ContextMessage(role=role, content=content, metadata=metadata_dict)
    if isinstance(value, str):
        return ContextMessage(role=(default_role or "system"), content=value)
    raise ValueError(
        "assemble_context messages must be RetrievedItem, ContextMessage, dict, or string values"
    )


async def _invoke_bound_tool(
    tool_function: Any,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    run_buffers: BufferStore,
    session_buffers: BufferStore,
) -> Any:
    ctx = RunContext(
        deps=SimpleNamespace(
            buffer_store=run_buffers,
            buffer_store_registry={
                "run": run_buffers,
                "session": session_buffers,
            },
        ),
        model=TestModel(),
        usage=RunUsage(),
        tool_name=tool_name,
    )
    result = tool_function.function(ctx, **arguments)
    if inspect.isawaitable(result):
        return await result
    return result


def _normalize_tool_result(result: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(result, ToolReturn):
        metadata = {
            "return_type": "tool_return",
            "has_content": result.content is not None,
            "metadata": result.metadata if isinstance(result.metadata, dict) else {},
        }
        return _coerce_output_data(result.return_value), metadata
    return _coerce_output_data(result), {"return_type": "text"}


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
    supported_keys = {"mode"}
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported output(file) options: {', '.join(unknown)}")
    raw_mode = str(options.get("mode") or "append").strip().lower()
    write_mode = normalize_write_mode(raw_mode)
    if write_mode is None:
        write_mode = "append"
    return write_mode, None


def _build_cache_output_options(options: dict[str, Any]) -> tuple[str, str, int | None]:
    supported_keys = {"mode", "ttl"}
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported output(cache) options: {', '.join(unknown)}")

    raw_mode = str(options.get("mode") or "append").strip().lower()
    if raw_mode not in {"append", "replace"}:
        raise ValueError("output(cache) option 'mode' must be one of: append, replace")

    raw_ttl = str(options.get("ttl") or "session").strip()
    parsed_ttl = parse_cache_mode_value(raw_ttl)
    return raw_mode, str(parsed_ttl["mode"]), parsed_ttl.get("ttl_seconds")


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
        "refs_only": bool(record.get("refs_only")),
        "extension": record.get("extension"),
        "size_bytes": record.get("size_bytes"),
        "char_count": record.get("char_count"),
        "token_estimate": record.get("token_estimate"),
        "mtime_epoch": record.get("mtime_epoch"),
        "ctime_epoch": record.get("ctime_epoch"),
        "mtime": record.get("mtime"),
        "ctime": record.get("ctime"),
        "filename_dt": record.get("filename_dt"),
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


def _normalize_cache_record(*, ref: str, record: dict[str, Any] | None) -> RetrievedItem:
    if record is None:
        return RetrievedItem(
            ref=ref,
            content="",
            exists=False,
            metadata={},
        )
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "cache_mode": record.get("cache_mode"),
            "ttl_seconds": record.get("ttl_seconds"),
            "origin": record.get("origin"),
            "created_at": record.get("created_at"),
            "last_accessed_at": record.get("last_accessed_at"),
            "expires_at": record.get("expires_at"),
        }
    )
    return RetrievedItem(
        ref=ref,
        content=str(record.get("raw_content") or ""),
        exists=True,
        metadata=metadata,
    )
