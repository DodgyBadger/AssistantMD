"""Shared typed tool binding for workflow authoring surfaces."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Type

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    ImageUrl,
    ToolReturn,
    VideoUrl,
)

from core.logger import UnifiedLogger
from core.settings import get_routing_allowed_tools
from core.settings.secrets_store import secret_has_value
from core.settings.store import ToolConfig, get_tools_config
from core.tools.base import BaseTool
from core.tools.utils import get_tool_instructions
from core.utils.routing import build_manifest, write_output
from core.authoring.shared.output_resolution import (
    normalize_write_mode,
    parse_output_value,
    resolve_output_request,
)
from core.directives.parser import DirectiveValueParser


logger = UnifiedLogger(tag="workflow-tool-binding")
TOOLS_ALLOWED_PARAMETERS = {"output", "write-mode", "write_mode", "scope"}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: Dict[str, str]
    tool_class: Type
    tool_function: object
    week_start_day: int = 0


@dataclass(frozen=True)
class ToolBindingResult:
    tool_functions: list[object]
    tool_instructions: str
    tool_specs: list[ToolSpec]

    def tool_names(self) -> list[str]:
        return [spec.name for spec in self.tool_specs]


def validate_tool_binding_value(value: Any) -> bool:
    """Validate string/list based tool declarations."""
    try:
        _normalize_tool_value(value, allow_empty=False)
    except Exception:
        return False

    normalized = _normalize_tool_value(value, allow_empty=False)
    if DirectiveValueParser.is_empty(normalized):
        return False

    lowered = DirectiveValueParser.normalize_string(normalized, to_lower=True)
    if lowered in ["true", "false", "yes", "no", "1", "0", "on", "off", "all", "none"]:
        return True

    items = _parse_tools_with_params(normalized)
    if not items:
        return False
    available_tools = set(get_tools_config().keys())
    return all(item[0] in available_tools for item in items)


def resolve_tool_binding(
    value: Any,
    *,
    vault_path: str,
    week_start_day: int = 0,
) -> ToolBindingResult:
    """Resolve workflow tools from DSL text or SDK literals."""
    normalized_value = _normalize_tool_value(value, allow_empty=False)
    if DirectiveValueParser.is_empty(normalized_value):
        raise ValueError("Tools directive requires explicit value - tools disabled by default for security")

    normalized = DirectiveValueParser.normalize_string(normalized_value, to_lower=True)
    tool_params_by_name: Dict[str, Dict[str, str]] = {}

    if normalized in ["true", "yes", "1", "on", "all"]:
        tool_names = list(get_tools_config().keys())
    elif normalized in ["false", "no", "0", "off", "none"]:
        return ToolBindingResult(tool_functions=[], tool_instructions="", tool_specs=[])
    else:
        parsed_tools = _parse_tools_with_params(normalized_value)
        tool_names = []
        for name, params in parsed_tools:
            if name not in tool_names:
                tool_names.append(name)
            if params:
                tool_params_by_name[name] = params

    configs = get_tools_config()
    tool_classes: list[Type] = []
    tool_functions: list[object] = []
    tool_specs: list[ToolSpec] = []
    skipped_tools: list[tuple[str, list[str]]] = []

    for tool_name in tool_names:
        config = configs.get(tool_name)
        if config is None:
            continue

        required_secrets = config.required_secret_keys()
        missing_secrets = [key for key in required_secrets if not secret_has_value(key)]
        if missing_secrets:
            skipped_tools.append((tool_name, missing_secrets))
            logger.warning(
                "Tool skipped due to missing secrets",
                metadata={"tool": tool_name, "missing_secrets": missing_secrets},
            )
            continue

        try:
            tool_class = _load_tool_class(tool_name)
            tool_classes.append(tool_class)
            tool_function = tool_class.get_tool(vault_path=vault_path)
            wrapped_tool = _wrap_tool_function(
                tool_function,
                tool_name=tool_name,
                params=tool_params_by_name.get(tool_name, {}),
                vault_path=vault_path,
                week_start_day=week_start_day,
                tool_instructions=tool_class.get_instructions(),
                tool_class=tool_class,
            )
            tool_functions.append(wrapped_tool)
            tool_specs.append(
                ToolSpec(
                    name=tool_name,
                    params=dict(tool_params_by_name.get(tool_name, {})),
                    tool_class=tool_class,
                    tool_function=wrapped_tool,
                    week_start_day=week_start_day,
                )
            )
        except Exception as exc:
            raise ValueError(f"Failed to load tool '{tool_name}': {exc}") from exc

    tool_instructions = get_tool_instructions(tool_classes) if tool_classes else ""
    if skipped_tools:
        skipped_messages = [
            f"{name} (missing {', '.join(missing)})" for name, missing in skipped_tools
        ]
        note = "NOTE: The following tools were unavailable and skipped: " + "; ".join(skipped_messages)
        tool_instructions = (tool_instructions + "\n\n" + note).strip()

    return ToolBindingResult(
        tool_functions=tool_functions,
        tool_instructions=tool_instructions,
        tool_specs=tool_specs,
    )


def merge_tool_bindings(results: list[Any]) -> ToolBindingResult:
    """Merge repeated tool declarations across directives/sections."""
    if not results:
        return ToolBindingResult(tool_functions=[], tool_instructions="", tool_specs=[])

    specs_by_name: Dict[str, ToolSpec] = {}
    fallback_functions: list[object] = []
    notes: list[str] = []

    for result in results:
        binding = _coerce_binding_result(result)
        if binding is None:
            continue
        for line in (binding.tool_instructions or "").splitlines():
            if line.strip().startswith("NOTE:"):
                notes.append(line.strip())
        for spec in binding.tool_specs:
            specs_by_name[spec.name] = spec
        if not binding.tool_specs:
            for fn in binding.tool_functions:
                if fn not in fallback_functions:
                    fallback_functions.append(fn)

    tool_specs = list(specs_by_name.values())
    tool_classes = [spec.tool_class for spec in tool_specs]
    tool_functions = [spec.tool_function for spec in tool_specs] if tool_specs else fallback_functions
    tool_instructions = get_tool_instructions(tool_classes) if tool_classes else ""

    if notes:
        unique_notes: list[str] = []
        for note in notes:
            if note not in unique_notes:
                unique_notes.append(note)
        note_block = "\n".join(unique_notes)
        tool_instructions = (tool_instructions + "\n\n" + note_block).strip() if tool_instructions else note_block

    return ToolBindingResult(
        tool_functions=tool_functions,
        tool_instructions=tool_instructions,
        tool_specs=tool_specs,
    )


def _coerce_binding_result(result: Any) -> ToolBindingResult | None:
    if isinstance(result, ToolBindingResult):
        return result
    if isinstance(result, tuple):
        if len(result) >= 3:
            return ToolBindingResult(
                tool_functions=list(result[0] or []),
                tool_instructions=result[1] or "",
                tool_specs=list(result[2] or []),
            )
        if len(result) == 2:
            return ToolBindingResult(
                tool_functions=list(result[0] or []),
                tool_instructions=result[1] or "",
                tool_specs=[],
            )
    return None


def _normalize_tool_value(value: Any, *, allow_empty: bool) -> str:
    if isinstance(value, ToolBindingResult):
        return ", ".join(value.tool_names())
    if isinstance(value, bool):
        return "all" if value else "none"
    if value is None:
        if allow_empty:
            return ""
        raise ValueError("Tools value cannot be empty")
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("tools= entries must be strings")
            normalized = item.strip()
            if normalized:
                parts.append(normalized)
        joined = ", ".join(parts)
        if joined or allow_empty:
            return joined
        raise ValueError("Tools value cannot be empty")
    if not isinstance(value, str):
        raise ValueError("tools= must be a string, boolean, or list of strings")
    normalized = value.strip()
    if normalized or allow_empty:
        return normalized
    raise ValueError("Tools value cannot be empty")


def _get_tool_configs() -> Dict[str, ToolConfig]:
    return get_tools_config()


def _load_tool_class(tool_name: str) -> Type:
    configs = _get_tool_configs()
    if tool_name not in configs:
        available_tools = ", ".join(configs.keys())
        raise ValueError(f"Unknown tool '{tool_name}'. Available tools: {available_tools}")

    config = configs[tool_name]
    try:
        module = importlib.import_module(config.module)
    except ImportError as exc:
        raise ValueError(f"Could not import module '{config.module}' for tool '{tool_name}': {exc}") from exc

    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj != BaseTool and issubclass(obj, BaseTool):
            return obj
    raise ValueError(f"No BaseTool subclass found in module '{config.module}' for tool '{tool_name}'")


def _tokenize_tools(value: str) -> list[str]:
    tokens: list[str] = []
    if DirectiveValueParser.is_empty(value):
        return tokens
    buf: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
        if depth == 0 and (ch == "," or ch.isspace()):
            token = "".join(buf).strip()
            if token:
                tokens.append(token)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        tokens.append(tail)
    return tokens


def _parse_tools_with_params(value: str) -> list[tuple[str, Dict[str, str]]]:
    tokens = _tokenize_tools(value)
    parsed: list[tuple[str, Dict[str, str]]] = []
    for token in tokens:
        base, params = DirectiveValueParser.parse_value_with_parameters(
            token,
            allowed_parameters=TOOLS_ALLOWED_PARAMETERS,
        )
        if not base:
            continue
        parsed.append((base.strip().lower(), params))
    return parsed


def _has_multimodal_tool_payload(result: object) -> bool:
    if not isinstance(result, ToolReturn):
        return False
    content = result.content
    if content is None or isinstance(content, str):
        return False
    for item in content:
        if isinstance(item, (BinaryContent, ImageUrl, AudioUrl, DocumentUrl, VideoUrl)):
            return True
    return False


def _wrap_tool_function(
    tool,
    *,
    tool_name: str,
    params: Dict[str, str],
    vault_path: str,
    week_start_day: int,
    tool_instructions: str | None = None,
    tool_class: Type | None = None,
):
    if tool_name == "buffer_ops":
        return tool
    original_func = tool.function
    original_takes_ctx = getattr(tool, "takes_ctx", False)
    allowed_tools = get_routing_allowed_tools()
    allow_output_params = tool_name in allowed_tools and getattr(tool_class, "allow_routing", True)

    async def _call_async(ctx: RunContext, **kwargs):
        output_value = kwargs.pop("output", None) if allow_output_params else None
        write_mode_value = kwargs.pop("write_mode", None) if allow_output_params else None
        try:
            if original_takes_ctx:
                result = await original_func(ctx, **kwargs)
            else:
                result = await original_func(**kwargs)
        except TypeError as exc:
            return _format_tool_type_error(tool_name, exc, tool_instructions)
        return _route_tool_output(
            result,
            tool_name=tool_name,
            output_value=output_value,
            write_mode_value=write_mode_value,
            params=params,
            vault_path=vault_path,
            week_start_day=week_start_day,
            buffer_store=getattr(ctx, "deps", None) and ctx.deps.buffer_store,
            buffer_store_registry=getattr(ctx, "deps", None) and ctx.deps.buffer_store_registry,
        )

    def _call_sync(ctx: RunContext, **kwargs):
        output_value = kwargs.pop("output", None) if allow_output_params else None
        write_mode_value = kwargs.pop("write_mode", None) if allow_output_params else None
        try:
            if original_takes_ctx:
                result = original_func(ctx, **kwargs)
            else:
                result = original_func(**kwargs)
        except TypeError as exc:
            return _format_tool_type_error(tool_name, exc, tool_instructions)
        return _route_tool_output(
            result,
            tool_name=tool_name,
            output_value=output_value,
            write_mode_value=write_mode_value,
            params=params,
            vault_path=vault_path,
            week_start_day=week_start_day,
            buffer_store=getattr(ctx, "deps", None) and ctx.deps.buffer_store,
            buffer_store_registry=getattr(ctx, "deps", None) and ctx.deps.buffer_store_registry,
        )

    wrapper = _call_async if inspect.iscoroutinefunction(original_func) else _call_sync
    try:
        sig = inspect.signature(original_func)
        params_list = list(sig.parameters.values())
        existing = {p.name for p in params_list}
        if not original_takes_ctx:
            ctx_param = inspect.Parameter(
                "ctx",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=RunContext,
            )
            params_list = [ctx_param] + params_list
        extra_params = []
        if allow_output_params and "output" not in existing:
            extra_params.append(inspect.Parameter("output", inspect.Parameter.KEYWORD_ONLY, default=None))
        if allow_output_params and "write_mode" not in existing:
            extra_params.append(inspect.Parameter("write_mode", inspect.Parameter.KEYWORD_ONLY, default=None))
        if extra_params:
            if params_list and params_list[-1].kind == inspect.Parameter.VAR_KEYWORD:
                params_list = params_list[:-1] + extra_params + [params_list[-1]]
            else:
                params_list.extend(extra_params)
        wrapper.__signature__ = sig.replace(parameters=params_list)
    except (ValueError, TypeError):
        pass

    wrapper.__name__ = getattr(original_func, "__name__", tool_name)
    wrapper.__doc__ = getattr(original_func, "__doc__", None)
    annotations = dict(getattr(original_func, "__annotations__", {}) or {})
    if not original_takes_ctx:
        annotations["ctx"] = RunContext
    if allow_output_params and "output" not in annotations:
        annotations["output"] = Optional[str]
    if allow_output_params and "write_mode" not in annotations:
        annotations["write_mode"] = Optional[str]
    wrapper.__annotations__ = annotations

    return type(tool)(
        wrapper,
        takes_ctx=True,
        name=getattr(tool, "name", None) or tool_name,
        description=getattr(tool, "description", None),
    )


def _route_tool_output(
    result,
    *,
    tool_name: str,
    output_value: str | None,
    write_mode_value: str | None,
    params: Dict[str, str],
    vault_path: str,
    week_start_day: int,
    buffer_store=None,
    buffer_store_registry=None,
):
    if tool_name == "buffer_ops":
        return result
    hard_output = params.get("output")
    output_target = hard_output or output_value
    scope_value = params.get("scope")
    if _has_multimodal_tool_payload(result):
        if output_target and output_target.strip().lower() != "inline":
            logger.warning(
                "Bypassing tool output routing for multimodal tool return",
                metadata={"tool": tool_name, "output_target": output_target},
            )
        return result
    if output_target is None:
        return result

    if hard_output is not None and hard_output.strip().lower() == "inline":
        return result

    write_mode_param = params.get("write-mode") or params.get("write_mode")
    write_mode = normalize_write_mode(write_mode_param or write_mode_value)
    try:
        parsed_target = resolve_output_request(
            parse_output_value(output_target),
            vault_path=vault_path,
            reference_date=datetime.now(),
            week_start_day=week_start_day,
        )
    except Exception as exc:
        return f"Invalid output target: {exc}. Use output=\"variable:NAME\" or output=\"file:PATH\"."

    if parsed_target.type == "inline":
        return result

    content = "" if result is None else (result if isinstance(result, str) else str(result))
    if parsed_target.type == "discard":
        manifest = build_manifest(
            source=tool_name,
            destination="discard",
            item_count=1,
            total_chars=len(content),
        )
        logger.set_sinks(["validation"]).info(
            "tool_output_routed",
            data={
                "event": "tool_output_routed",
                "tool": tool_name,
                "destination": "discard",
                "write_mode": write_mode or "append",
                "output_chars": len(content),
                "forced": hard_output is not None,
            },
        )
        return manifest

    default_scope = "run"
    if buffer_store_registry and "session" in buffer_store_registry and "run" not in buffer_store_registry:
        default_scope = "session"
    write_result = write_output(
        target=parsed_target.target,
        content=content,
        write_mode=write_mode,
        buffer_store=buffer_store,
        buffer_store_registry=buffer_store_registry,
        vault_path=vault_path,
        buffer_scope=parsed_target.buffer_scope or scope_value,
        default_scope=default_scope,
    )
    destination = ""
    if write_result.get("type") == "buffer":
        destination = f"variable: {write_result.get('name')}"
    elif write_result.get("type") == "file":
        destination = f"file: {write_result.get('path')}"
    else:
        destination = parsed_target.type
    manifest = build_manifest(
        source=tool_name,
        destination=destination,
        item_count=1,
        total_chars=len(content),
    )
    logger.set_sinks(["validation"]).info(
        "tool_output_routed",
        data={
            "event": "tool_output_routed",
            "tool": tool_name,
            "destination": destination,
            "write_mode": write_mode or "append",
            "output_chars": len(content),
            "forced": hard_output is not None,
        },
    )
    return manifest


def _format_tool_type_error(tool_name: str, exc: Exception, instructions: str | None) -> str:
    prefix = f"Invalid parameters for tool '{tool_name}': {exc}. Use named parameters only."
    if instructions:
        return f"{prefix}\n\n{instructions}"
    return prefix
