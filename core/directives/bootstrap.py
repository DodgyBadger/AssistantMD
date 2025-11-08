"""
Helpers for registering built-in directive processors.

Provides an explicit entry point for wiring the default directive set into the
global registry without relying on package import side effects.
"""

from __future__ import annotations

from typing import Type

from core.logger import UnifiedLogger

from .base import DirectiveProcessor
from .header import HeaderDirective
from .input_file import InputFileDirective
from .model import ModelDirective
from .output_file import OutputFileDirective
from .registry import get_global_registry
from .run_on import RunOnDirective
from .tools import ToolsDirective
from .write_mode import WriteModeDirective

logger = UnifiedLogger(tag="directive-bootstrap")

_BUILTIN_DIRECTIVES: tuple[Type[DirectiveProcessor], ...] = (
    OutputFileDirective,
    InputFileDirective,
    RunOnDirective,
    ModelDirective,
    WriteModeDirective,
    ToolsDirective,
    HeaderDirective,
)

_builtins_registered: bool = False


def ensure_builtin_directives_registered(force: bool = False) -> None:
    """Register the built-in directive processors with the global registry.

    Args:
        force: Re-register processors even if they've already been added.
    """
    global _builtins_registered

    if _builtins_registered and not force:
        return

    registry = get_global_registry()

    for directive_cls in _BUILTIN_DIRECTIVES:
        directive = directive_cls()
        directive_name = directive.get_directive_name()

        if not force and registry.is_directive_registered(directive_name):
            continue

        try:
            registry.register_directive(directive)
        except Exception as exc:
            logger.error(
                "Failed to register directive",
                directive=directive_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

    _builtins_registered = True
