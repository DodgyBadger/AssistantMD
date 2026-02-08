"""
Tools directive processor.

Handles @tools directive for per-step tool selection using granular tool names.
Loads and returns actual tool instances ready for agent use.
"""

import importlib
import inspect
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Type, Tuple, Optional, Any

from core.logger import UnifiedLogger
from pydantic_ai import RunContext
from core.settings.store import get_tools_config, ToolConfig
from core.tools.utils import get_tool_instructions
from core.tools.base import BaseTool
from core.settings.secrets_store import secret_has_value
from core.settings import get_auto_buffer_max_tokens
from core.tools.utils import estimate_token_count
from core.utils.routing import (
    build_manifest,
    normalize_write_mode,
    parse_output_target,
    write_output,
    OutputTarget,
)
from .base import DirectiveProcessor
from .parser import DirectiveValueParser


logger = UnifiedLogger(tag="directive-tools")


class ToolsDirective(DirectiveProcessor):
    """Processor for @tools directive that specifies which tools to enable for a step."""

    @dataclass
    class ToolSpec:
        name: str
        params: Dict[str, str]
        tool_class: Type
        tool_function: object
        week_start_day: int = 0

    def _wrap_tool_function(
        self,
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
        allow_output_params = getattr(tool_class, "allow_routing", True) if tool_class else tool_name != "buffer_ops"

        async def _call_async(ctx: RunContext, **kwargs):
            output_value = kwargs.pop("output", None) if allow_output_params else None
            write_mode_value = kwargs.pop("write_mode", None) if allow_output_params else None

            try:
                if original_takes_ctx:
                    result = await original_func(ctx, **kwargs)
                else:
                    result = await original_func(**kwargs)
            except TypeError as exc:
                return self._format_tool_type_error(tool_name, exc, tool_instructions)

            return self._route_tool_output(
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
                return self._format_tool_type_error(tool_name, exc, tool_instructions)

            return self._route_tool_output(
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

        is_async = inspect.iscoroutinefunction(original_func)
        wrapper = _call_async if is_async else _call_sync

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
                extra_params.append(
                    inspect.Parameter("output", inspect.Parameter.KEYWORD_ONLY, default=None)
                )
            if allow_output_params and "write_mode" not in existing:
                extra_params.append(
                    inspect.Parameter("write_mode", inspect.Parameter.KEYWORD_ONLY, default=None)
                )
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
        self,
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
        if output_target is None:
            auto_limit = get_auto_buffer_max_tokens()
            if auto_limit and auto_limit > 0:
                content = "" if result is None else (result if isinstance(result, str) else str(result))
                if content:
                    token_count = estimate_token_count(content)
                    if token_count > auto_limit:
                        default_scope = "run"
                        if buffer_store_registry and "session" in buffer_store_registry and "run" not in buffer_store_registry:
                            default_scope = "session"
                        auto_name = f"{tool_name}_output"
                        write_result = write_output(
                            target=OutputTarget(type="buffer", name=auto_name),
                            content=content,
                            write_mode="new",
                            buffer_store=buffer_store,
                            buffer_store_registry=buffer_store_registry,
                            vault_path=vault_path,
                            buffer_scope=scope_value,
                            default_scope=default_scope,
                            metadata={"auto_buffered": True, "token_count": token_count},
                        )
                        destination = f"variable: {write_result.get('name')}"
                        manifest = build_manifest(
                            source=tool_name,
                            destination=destination,
                            item_count=1,
                            total_chars=len(content),
                            note=(
                                f"Auto-buffered output ({token_count} tokens > {auto_limit}). "
                                f"Read with buffer_ops, e.g. buffer_ops(operation=\"peek\", "
                                f"target=\"{write_result.get('name')}\", max_chars=1000)."
                            ),
                        )
                        logger.set_sinks(["validation"]).info(
                            "tool_output_routed",
                            data={
                                "event": "tool_output_routed",
                                "tool": tool_name,
                                "destination": destination,
                                "write_mode": write_result.get("write_mode", "append"),
                                "output_chars": len(content),
                                "forced": True,
                                "auto_buffered": True,
                                "token_count": token_count,
                                "token_limit": auto_limit,
                            },
                        )
                        return manifest
            return result

        if hard_output is not None and hard_output.strip().lower() == "inline":
            return result

        write_mode_param = params.get("write-mode") or params.get("write_mode")
        write_mode = normalize_write_mode(write_mode_param or write_mode_value)

        try:
            parsed_target = parse_output_target(
                output_target,
                vault_path,
                reference_date=datetime.now(),
                week_start_day=week_start_day,
            )
        except Exception as exc:
            return (
                f"Invalid output target: {exc}. "
                'Use output="variable:NAME" or output="file:PATH".'
            )

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
            target=parsed_target,
            content=content,
            write_mode=write_mode,
            buffer_store=buffer_store,
            buffer_store_registry=buffer_store_registry,
            vault_path=vault_path,
            buffer_scope=scope_value,
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

    @staticmethod
    def _format_tool_type_error(tool_name: str, exc: Exception, instructions: str | None) -> str:
        prefix = (
            f"Invalid parameters for tool '{tool_name}': {exc}. "
            "Use named parameters only."
        )
        if instructions:
            return f"{prefix}\n\n{instructions}"
        return prefix

    def get_directive_name(self) -> str:
        return "tools"

    def _get_tool_configs(self) -> Dict[str, ToolConfig]:
        """Load tool configurations from settings.yaml."""
        return get_tools_config()
    
    def _load_tool_class(self, tool_name: str) -> Type:
        """Dynamically load a tool class by name using introspection."""
        configs = self._get_tool_configs()
        if tool_name not in configs:
            available_tools = ', '.join(configs.keys())
            raise ValueError(f"Unknown tool '{tool_name}'. Available tools: {available_tools}")

        config = configs[tool_name]
        module_path = config.module
        
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ValueError(f"Could not import module '{module_path}' for tool '{tool_name}': {e}")
        
        # Find the BaseTool subclass in the module
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj != BaseTool and issubclass(obj, BaseTool):
                return obj
        
        raise ValueError(f"No BaseTool subclass found in module '{module_path}' for tool '{tool_name}'")

    def _tokenize_tools(self, value: str) -> List[str]:
        tokens: List[str] = []
        if DirectiveValueParser.is_empty(value):
            return tokens
        buf: List[str] = []
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

    def _parse_tools_with_params(self, value: str) -> List[Tuple[str, Dict[str, str]]]:
        tokens = self._tokenize_tools(value)
        parsed: List[Tuple[str, Dict[str, str]]] = []
        for token in tokens:
            base, params = DirectiveValueParser.parse_value_with_parameters(
                token,
                allowed_parameters={"output", "write-mode", "write_mode", "scope"},
            )
            if not base:
                continue
            parsed.append((base.strip().lower(), params))
        return parsed
    
    def validate_value(self, value: str) -> bool:
        """Validate tools directive value.
        
        Accepts:
        - 'true', 'yes', '1', 'on' (enable all available tools)
        - 'false', 'no', '0', 'off' (disable all tools)
        - Tool names: 'web_search', 'code_execution', etc.
        - Special keywords: 'all', 'none'
        - Lists: 'web_search, code_execution' or 'web_search code_execution'
        
        Note: Empty value is invalid - tools must be explicitly enabled
        """
        if DirectiveValueParser.is_empty(value):
            return False  # Empty means no tools specified - invalid
        
        # Check if it's a boolean value
        normalized = DirectiveValueParser.normalize_string(value, to_lower=True)
        if normalized in ['true', 'false', 'yes', 'no', '1', '0', 'on', 'off']:
            return True
        
        # Check if it's special keywords
        if normalized in ['all', 'none']:
            return True
        
        # Parse as list and validate against available tools
        items = self._parse_tools_with_params(value)
        if not items:
            return False
        
        # Validate all tools exist in configuration
        available_tools = set(self._get_tool_configs().keys())
        return all(item[0] in available_tools for item in items)
    
    def process_value(self, value: str, vault_path: str, **context) -> Tuple[List, str, List["ToolsDirective.ToolSpec"]]:
        """Process tools directive value and return tool functions and enhanced instructions.
        
        Returns:
            Tuple of (tool_functions, enhanced_instructions, tool_specs) where:
            - tool_functions: List of Pydantic AI tool functions ready for agent use
            - enhanced_instructions: Instructions text enhanced with tool descriptions
            - tool_specs: Parsed tool specs with params
        """
        if DirectiveValueParser.is_empty(value):
            raise ValueError("Tools directive requires explicit value - tools disabled by default for security")
        
        normalized = DirectiveValueParser.normalize_string(value, to_lower=True)
        tool_params_by_name: Dict[str, Dict[str, str]] = {}
        week_start_day = context.get("week_start_day", 0)
        
        # Handle boolean values
        if normalized in ['true', 'yes', '1', 'on']:
            # Enable all available tools
            tool_names = list(self._get_tool_configs().keys())
        elif normalized in ['false', 'no', '0', 'off', 'none']:
            # No tools - return empty tools and empty instructions
            return [], "", []
        elif normalized == 'all':
            # Enable all available tools
            tool_names = list(self._get_tool_configs().keys())
        else:
            # Parse as specific tool list
            parsed_tools = self._parse_tools_with_params(value)
            tool_names = []
            for name, params in parsed_tools:
                if name not in tool_names:
                    tool_names.append(name)
                if params:
                    tool_params_by_name[name] = params
        
        configs = self._get_tool_configs()

        # Load tool classes and extract tool functions
        tool_classes = []
        tool_functions = []
        tool_specs: List[ToolsDirective.ToolSpec] = []
        skipped_tools: List[Tuple[str, List[str]]] = []
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
                tool_class = self._load_tool_class(tool_name)
                tool_classes.append(tool_class)
                # Extract the Pydantic AI tool function with vault context
                tool_function = tool_class.get_tool(vault_path=vault_path)
                wrapped_tool = self._wrap_tool_function(
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
                    ToolsDirective.ToolSpec(
                        name=tool_name,
                        params=dict(tool_params_by_name.get(tool_name, {})),
                        tool_class=tool_class,
                        tool_function=wrapped_tool,
                        week_start_day=week_start_day,
                    )
                )
            except Exception as e:
                raise ValueError(f"Failed to load tool '{tool_name}': {e}")

        # Generate enhanced instructions using existing helper function
        enhanced_instructions = get_tool_instructions(tool_classes) if tool_classes else ""

        if skipped_tools:
            skipped_messages = [
                f"{name} (missing {', '.join(missing)})" for name, missing in skipped_tools
            ]
            note = (
                "NOTE: The following tools were unavailable and skipped: "
                + "; ".join(skipped_messages)
            )
            enhanced_instructions = (enhanced_instructions + "\n\n" + note).strip()

        return tool_functions, enhanced_instructions, tool_specs

    @staticmethod
    def merge_results(results: List[Tuple]) -> Tuple[List, str, List["ToolsDirective.ToolSpec"]]:
        if not results:
            return [], "", []

        specs_by_name: Dict[str, ToolsDirective.ToolSpec] = {}
        fallback_functions: List[object] = []
        notes: List[str] = []

        for result in results:
            if not isinstance(result, tuple):
                continue
            if len(result) >= 2:
                instructions = result[1] or ""
                for line in instructions.splitlines():
                    if line.strip().startswith("NOTE:"):
                        notes.append(line.strip())
            if len(result) >= 3:
                specs = result[2] or []
                for spec in specs:
                    specs_by_name[spec.name] = spec
            else:
                funcs = result[0] or []
                for fn in funcs:
                    if fn not in fallback_functions:
                        fallback_functions.append(fn)

        tool_specs = list(specs_by_name.values())
        tool_classes = [spec.tool_class for spec in tool_specs]
        tool_functions = [spec.tool_function for spec in tool_specs] if tool_specs else fallback_functions
        tool_instructions = get_tool_instructions(tool_classes) if tool_classes else ""

        if notes:
            unique_notes = []
            for note in notes:
                if note not in unique_notes:
                    unique_notes.append(note)
            note_block = "\n".join(unique_notes)
            tool_instructions = (tool_instructions + "\n\n" + note_block).strip() if tool_instructions else note_block

        return tool_functions, tool_instructions, tool_specs
