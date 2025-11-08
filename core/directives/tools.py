"""
Tools directive processor.

Handles @tools directive for per-step tool selection using granular tool names.
Loads and returns actual tool instances ready for agent use.
"""

import importlib
import inspect
from typing import List, Dict, Type, Tuple

from core.logger import UnifiedLogger
from core.settings.store import get_tools_config, ToolConfig
from core.tools.utils import get_tool_instructions
from core.tools.base import BaseTool
from core.settings.secrets_store import secret_has_value
from .base import DirectiveProcessor
from .parser import DirectiveValueParser


logger = UnifiedLogger(tag="directive-tools")


class ToolsDirective(DirectiveProcessor):
    """Processor for @tools directive that specifies which tools to enable for a step."""

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
        items = DirectiveValueParser.parse_list(value, to_lower=True)
        if not items:
            return False
        
        # Validate all tools exist in configuration
        available_tools = set(self._get_tool_configs().keys())
        return all(item in available_tools for item in items)
    
    def process_value(self, value: str, vault_path: str, **context) -> Tuple[List, str]:
        """Process tools directive value and return tool functions and enhanced instructions.
        
        Returns:
            Tuple of (tool_functions, enhanced_instructions) where:
            - tool_functions: List of Pydantic AI tool functions ready for agent use
            - enhanced_instructions: Instructions text enhanced with tool descriptions
        """
        if DirectiveValueParser.is_empty(value):
            raise ValueError("Tools directive requires explicit value - tools disabled by default for security")
        
        normalized = DirectiveValueParser.normalize_string(value, to_lower=True)
        
        # Handle boolean values
        if normalized in ['true', 'yes', '1', 'on']:
            # Enable all available tools
            tool_names = list(self._get_tool_configs().keys())
        elif normalized in ['false', 'no', '0', 'off', 'none']:
            # No tools - return empty tools and empty instructions
            return [], ""
        elif normalized == 'all':
            # Enable all available tools
            tool_names = list(self._get_tool_configs().keys())
        else:
            # Parse as specific tool list
            tool_names = DirectiveValueParser.parse_list(value, to_lower=True)
        
        configs = self._get_tool_configs()

        # Load tool classes and extract tool functions
        tool_classes = []
        tool_functions = []
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
                tool_functions.append(tool_function)
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

        return tool_functions, enhanced_instructions
