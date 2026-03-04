from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage

from core.context.templates import TemplateRecord, TemplateSection
from core.runtime.buffers import BufferStore


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


@dataclass
class ContextManagerInput:
    """Minimal inputs needed to manage/curate a working context."""

    model_alias: str
    template: TemplateRecord
    template_section: Optional[TemplateSection]
    context_payload: Dict[str, Any]


@dataclass
class ContextManagerResult:
    """Result of a context management run."""

    raw_output: str
    template: TemplateRecord
    model_alias: str


@dataclass
class ContextManagerDeps:
    """Dependencies for context manager tool execution."""

    buffer_store: BufferStore
    buffer_store_registry: dict[str, BufferStore]


@dataclass
class InputResolutionResult:
    input_file_data: Optional[Any]
    input_files_prompt: Optional[Any]
    context_input_outputs: List[str]
    empty_input_file_directive: bool
    skip_required: bool


@dataclass
class CacheDecision:
    managed_output: Optional[str]
    managed_model_alias: str
    cache_hit_scope: Optional[str]
    cache_mode: Optional[str]


@dataclass
class OutputRoutingResult:
    written_buffers: List[str]
    written_files: List[str]


@dataclass
class SectionExecutionContext:
    session_id: str
    vault_name: str
    vault_path: str
    model_alias: str
    template: TemplateRecord
    registry: Any
    week_start_day: int
    manager_runs: int
    recent_summaries_default: int
    run_context: RunContext[Any]
    cache_enabled: bool
    cache_store: Dict[str, Any]
    cache_entry: Dict[str, Any]
    section_cache: Dict[str, Any]
    run_scope_key: Optional[str]
    run_buffer_store: BufferStore
    buffer_store_registry: Dict[str, BufferStore]


@dataclass
class SectionExecutionResult:
    summary_messages: List[ModelMessage]
    persisted_sections: List[Dict[str, str]]
    output_routing: Optional[OutputRoutingResult] = None


ManageContextFn = Callable[
    [ContextManagerInput],
    Awaitable[ContextManagerResult],
]
