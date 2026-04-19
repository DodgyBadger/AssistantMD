"""Definition and execution for the generate(...) Monty helper."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    GenerationResult,
    RetrievedItem,
)
from core.authoring.helpers.common import build_capability
from core.authoring.helpers.runtime_common import coerce_output_data, normalize_retrieved_items_input
from core.authoring.shared.execution_prep import build_step_prompt, resolve_step_model_execution
from core.authoring.shared.tool_binding import resolve_tool_binding
from core.authoring.cache import parse_cache_mode_value
from core.llm.model_factory import build_model_instance
from core.llm.model_selection import ModelExecutionSpec
from core.llm.thinking import ThinkingValue, normalize_thinking_value, thinking_value_to_label
from core.authoring.cache import get_cache_artifact, purge_expired_cache_artifacts, upsert_cache_artifact
from core.logger import UnifiedLogger
from core.settings import get_default_model_thinking


logger = UnifiedLogger(tag="authoring-host")
_THINKING_UNSET = object()


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="generate",
        doc="Run an explicit model generation within frontmatter policy.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> GenerationResult:
    from core.llm.agents import create_agent, generate_response

    host = context.host
    prompt, inputs, instructions, model_value, tool_names, cache_policy, options = _parse_call(call)
    requested_thinking = _parse_generate_thinking_option(options)
    default_thinking = get_default_model_thinking()
    resolved_thinking, thinking_source = _resolve_effective_thinking(
        requested_thinking=requested_thinking,
        default_thinking=default_thinking,
    )
    prompt_input: Any = prompt
    attached_image_count = 0
    input_warnings: list[str] = []

    if inputs:
        model_execution = resolve_step_model_execution(model_value)
        prompt_input, _prompt_text, attached_image_count, input_warnings = build_step_prompt(
            base_prompt=prompt,
            input_file_data=_build_input_file_data(inputs),
            vault_path=host.vault_path or "",
            model_execution=model_execution,
        )

    cache_mode: str | None = None
    cache_ttl_seconds: int | None = None
    cache_ref: str | None = None
    if cache_policy is not None:
        cache_mode, cache_ttl_seconds = _parse_cache_policy(cache_policy)
        cache_ref = _build_cache_ref(
            prompt=prompt,
            inputs=inputs,
            instructions=instructions,
            model_value=model_value or "default",
            tool_names=tool_names,
            cache_mode=cache_mode,
            ttl_seconds=cache_ttl_seconds,
            thinking_value=thinking_value_to_label(resolved_thinking),
        )
        purge_expired_cache_artifacts(now=host.reference_date)
        cached = get_cache_artifact(
            owner_id=context.workflow_id,
            session_key=host.session_key,
            artifact_ref=cache_ref,
            now=host.reference_date,
            week_start_day=host.week_start_day,
        )
        if cached is not None:
            logger.add_sink("validation").info(
                "authoring_generate_cache_hit",
                data={
                    "workflow_id": context.workflow_id,
                    "model": model_value or "default",
                    "cache_mode": cache_mode,
                    "cache_ref": cache_ref,
                    "output_chars": len(cached["raw_content"]),
                },
            )
            return GenerationResult(
                status="cached",
                model=model_value or "default",
                output=cached["raw_content"],
            )

    logger.add_sink("validation").info(
        "authoring_thinking_resolved",
        data={
            "workflow_id": context.workflow_id,
            "model": model_value or "default",
            "requested_thinking": thinking_value_to_label(
                None if requested_thinking is _THINKING_UNSET else requested_thinking
            ),
            "resolved_thinking": thinking_value_to_label(resolved_thinking),
            "source": thinking_source,
        },
    )

    model = None
    if model_value:
        model = build_model_instance(model_value, thinking=resolved_thinking)
        if isinstance(model, ModelExecutionSpec) and model.mode == "skip":
            raise ValueError("generate does not support skip model mode")

    logger.add_sink("validation").info(
        "authoring_generate_started",
        data={
            "workflow_id": context.workflow_id,
            "model": model_value or "default",
            "instructions_present": bool(instructions),
            "input_count": len(inputs),
            "attached_image_count": attached_image_count,
            "input_warnings": input_warnings,
            "tool_names": list(tool_names),
            "cache_mode": cache_mode,
            "resolved_thinking": thinking_value_to_label(resolved_thinking),
        },
    )

    bound_tools = None
    if tool_names:
        binding = resolve_tool_binding(
            list(tool_names),
            vault_path=host.vault_path or "",
            week_start_day=host.week_start_day,
        )
        bound_tools = binding.tool_functions

    agent = await create_agent(model=model, tools=bound_tools, thinking=resolved_thinking)
    if instructions:
        agent.instructions(lambda _ctx, text=instructions: text)
    output = await generate_response(agent, prompt_input)
    text = coerce_output_data(output)

    if cache_mode is not None and cache_ref is not None:
        upsert_cache_artifact(
            owner_id=context.workflow_id,
            session_key=host.session_key,
            artifact_ref=cache_ref,
            cache_mode=cache_mode,
            ttl_seconds=cache_ttl_seconds,
            raw_content=text,
            metadata={
                "kind": "generate",
                "model": model_value or "default",
                "prompt_chars": len(prompt),
                "instructions_present": bool(instructions),
                "tool_names": list(tool_names),
                "thinking": thinking_value_to_label(resolved_thinking),
            },
            origin="authoring_generate",
            now=host.reference_date,
            week_start_day=host.week_start_day,
        )
        logger.add_sink("validation").info(
            "authoring_generate_cache_stored",
            data={
                "workflow_id": context.workflow_id,
                "model": model_value or "default",
                "tool_names": list(tool_names),
                "cache_mode": cache_mode,
                "cache_ref": cache_ref,
                "output_chars": len(text),
            },
        )

    logger.add_sink("validation").info(
        "authoring_generate_completed",
        data={
            "workflow_id": context.workflow_id,
            "model": model_value or "default",
            "tool_names": list(tool_names),
            "output_chars": len(text),
        },
    )
    return GenerationResult(
        status="generated",
        model=model_value or "default",
        output=text,
    )


def _parse_call(
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

    inputs = normalize_retrieved_items_input(
        call.kwargs.get("inputs"),
        field_name="generate inputs",
    ) if "inputs" in call.kwargs else ()
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


def _parse_cache_policy(cache_value: str | dict[str, Any]) -> tuple[str, int | None]:
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


def _build_cache_ref(
    *,
    prompt: str,
    inputs: tuple[RetrievedItem, ...],
    instructions: str | None,
    model_value: str,
    tool_names: tuple[str, ...],
    cache_mode: str,
    ttl_seconds: int | None,
    thinking_value: str,
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
        "thinking": thinking_value,
    }
    digest = hashlib.sha256(
        json.dumps(cache_key_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"generate/{digest}"


def _build_input_file_data(inputs: tuple[RetrievedItem, ...]) -> list[dict[str, Any]]:
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


def _parse_generate_thinking_option(options: dict[str, Any]) -> object:
    supported_keys = {"thinking"}
    unknown = sorted(set(options) - supported_keys)
    if unknown:
        raise ValueError(f"Unsupported generate options: {', '.join(unknown)}")
    if "thinking" not in options:
        return _THINKING_UNSET
    return normalize_thinking_value(options["thinking"], source_name="generate option 'thinking'")


def _resolve_effective_thinking(
    *, requested_thinking: object, default_thinking: ThinkingValue
) -> tuple[ThinkingValue, str]:
    if requested_thinking is not _THINKING_UNSET:
        return requested_thinking, "call_override"  # type: ignore[return-value]
    if default_thinking is not None:
        return default_thinking, "global_default"
    return None, "provider_default"


def _contract() -> dict[str, object]:
    return {
        "signature": (
            "generate(*, prompt: str, inputs: RetrieveResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...] | None = None, instructions: str | None = None, "
            "model: str | None = None, tools: list[str] | tuple[str, ...] | None = None, "
            "cache: str | dict | None = None, options: dict | None = None)"
        ),
        "summary": (
            "Run one explicit model generation using the shared agent runtime. "
            "Instructions are first-class, while optional file-backed inputs, tool use, "
            "generation caching, and less common model controls stay explicit."
        ),
        "arguments": {
            "prompt": {
                "type": "string",
                "required": True,
                "description": "Primary user prompt passed to the shared agent runtime.",
            },
            "inputs": {
                "type": "RetrieveResult | RetrievedItem | list | tuple",
                "required": False,
                "description": (
                    "Optional retrieved file artifacts to assemble as source material. "
                    "Text files are inlined, direct images are attached when the model "
                    "supports vision, and markdown files may interleave embedded images "
                    "using the shared prompt builder."
                ),
            },
            "instructions": {
                "type": "string",
                "required": False,
                "description": "Additional system-style instructions layered onto the agent.",
            },
            "model": {
                "type": "string",
                "required": False,
                "description": "Optional model alias resolved through the shared model configuration.",
            },
            "tools": {
                "type": "list|tuple",
                "required": False,
                "description": (
                    "Optional explicit subset of available runtime tools for this generation. "
                    "When omitted, generate runs without tool use."
                ),
            },
            "cache": {
                "type": "string | object",
                "required": False,
                "description": (
                    "Optional host-managed generation cache policy. Use the same TTL "
                    "semantics as cache artifacts: session, daily, weekly, or a "
                    "duration like 10m/24h. Use this for generation memoization. "
                    "Use output(type=\"cache\", ...) when you want a named retrievable "
                    "cache artifact."
                ),
                "schema": {
                    "string_form": "session | daily | weekly | <duration>",
                    "object_form": {
                        "mode": {
                            "type": "string",
                            "description": "Cache mode using the same values as the string form.",
                        }
                    },
                },
            },
            "options": {
                "type": "object",
                "required": False,
                "description": "Less common generation controls.",
                "schema": {
                    "thinking": {
                        "type": "bool|string",
                        "description": "Optional thinking override. Use true/false or minimal, low, medium, high, xhigh.",
                    }
                },
            },
        },
        "return_shape": {
            "status": "High-level generation status such as generated or cached.",
            "model": "Resolved model alias or default indicator.",
            "output": "Generated output text.",
        },
        "notes": [
            (
                "generate(..., cache=...) provides host-managed memoization for repeated "
                "generation calls with the same inputs."
            ),
            (
                "Use output(type=\"cache\", ...) when you want a named retrievable "
                "artifact for later scripted access."
            ),
            (
                "Tool use is opt-in. Pass tools=[...] to enable an explicit subset "
                "of available runtime tools for one generation call."
            ),
            (
                "inputs=... reuses the shared file prompt builder. Use it when retrieved "
                "source material should stay file-aware, including images and embedded markdown images."
            ),
        ],
        "examples": [
            {
                "code": (
                    'await generate(prompt="Summarize this note", '
                    'instructions="Be concise and factual.")'
                ),
                "description": "Use the default model with extra instructions.",
            },
            {
                "code": (
                    'await generate(prompt="Draft a reply", instructions="Warm tone.", '
                    'model="test", options={"thinking": "high"})'
                ),
                "description": "Use an explicit model alias with a supported generation option.",
            },
            {
                "code": (
                    'image = await retrieve(type="file", ref="images/test_image.jpg")\n'
                    'await generate(prompt="Describe this image briefly.", inputs=image.items)'
                ),
                "description": "Attach one retrieved image file as model input when the model supports vision.",
            },
            {
                "code": (
                    'note = await retrieve(type="file", ref="notes/trip-report.md")\n'
                    'await generate('
                    'prompt="Summarize this note and its embedded images.", '
                    'inputs=note.items, '
                    'instructions="Be concise."'
                    ')'
                ),
                "description": "Feed one retrieved markdown file through the shared multimodal prompt builder.",
            },
            {
                "code": (
                    'note = await retrieve(type="file", ref="notes/today.md")\n'
                    'await generate(prompt="Summarize this note.", inputs=note.items)'
                ),
                "description": "Use inputs=... for plain text files too when you want host-managed source assembly.",
            },
            {
                "code": (
                    'await generate(prompt="Summarize and verify these leads.", '
                    'instructions="Use search sparingly and cite concrete event details.", '
                    'tools=["web_search_tavily"])'
                ),
                "description": "Enable tool use explicitly for one bounded generation call.",
            },
            {
                "code": (
                    'await generate(prompt="Summarize these notes", '
                    'instructions="Be concise.", model="test", cache="daily")'
                ),
                "description": "Cache a deterministic generation result using existing cache TTL semantics.",
            },
        ],
    }
