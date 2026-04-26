"""Type stubs for the Monty authoring runtime.

Passed to Monty's bundled type checker (ty) via ``type_check_stubs`` so that
capability calls and reserved input variables are fully typed in sandbox code.
"""

from typing import Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class RetrievedItem:
    ref: str | None
    content: str
    exists: bool
    metadata: dict[str, Any]

class RetrieveResult:
    type: str
    ref: str
    items: tuple[RetrievedItem, ...]

class GenerationResult:
    status: str
    model: str
    output: str

class ScriptToolResult:
    name: str
    status: str
    output: str
    metadata: dict[str, Any]
    content: Any | None
    items: tuple[RetrievedItem, ...]

class PendingFilesResult:
    operation: str
    status: str
    items: tuple[RetrievedItem, ...]
    completed_count: int

class ContextMessage:
    role: str
    content: str
    metadata: dict[str, Any]
    text: str
    def to_text(self) -> str: ...
    def __str__(self) -> str: ...

class HistoryMessage:
    role: str
    content: str
    message: dict[str, Any] | None
    metadata: dict[str, Any]
    text: str
    def to_text(self) -> str: ...
    def __str__(self) -> str: ...

class ToolExchange:
    tool_call_id: str
    tool_name: str
    request_message: dict[str, Any]
    response_message: dict[str, Any]
    call_arguments: dict[str, Any] | None
    result_text: str | None
    metadata: dict[str, Any]
    text: str
    def to_text(self) -> str: ...
    def __str__(self) -> str: ...

class RetrievedHistoryResult:
    source: str
    scope: str
    session_id: str | None
    item_count: int
    items: tuple[Any, ...]
    metadata: dict[str, Any]
    text: str

class LatestMessage:
    role: str
    content: str
    metadata: dict[str, Any]
    text: str
    exists: bool

class AssembleContextResult:
    messages: tuple[Any, ...]
    instructions: tuple[str, ...]

class MarkdownHeading:
    level: int
    text: str
    line_start: int

class MarkdownSection:
    heading: str
    level: int
    content: str
    line_start: int

class MarkdownCodeBlock:
    language: str | None
    content: str
    line_start: int | None

class MarkdownImage:
    src: str
    alt: str
    title: str | None
    line_start: int | None

class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str
    headings: tuple[MarkdownHeading, ...]
    sections: tuple[MarkdownSection, ...]
    code_blocks: tuple[MarkdownCodeBlock, ...]
    images: tuple[MarkdownImage, ...]

class FinishResult:
    status: str
    reason: str


# ---------------------------------------------------------------------------
# Reserved input variables
# ---------------------------------------------------------------------------

class MontyDateTokens:
    def today(self, fmt: str | None = None) -> str: ...
    def yesterday(self, fmt: str | None = None) -> str: ...
    def tomorrow(self, fmt: str | None = None) -> str: ...
    def this_week(self, fmt: str | None = None) -> str: ...
    def last_week(self, fmt: str | None = None) -> str: ...
    def next_week(self, fmt: str | None = None) -> str: ...
    def this_month(self, fmt: str | None = None) -> str: ...
    def last_month(self, fmt: str | None = None) -> str: ...
    def day_name(self, fmt: str | None = None) -> str: ...
    def month_name(self, fmt: str | None = None) -> str: ...

date: MontyDateTokens
latest_message: LatestMessage


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

async def read_cache(
    *,
    ref: str,
) -> RetrievedItem: ...

async def pending_files(
    *,
    operation: str,
    items: ScriptToolResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...],
) -> PendingFilesResult: ...

async def generate(
    *,
    prompt: str,
    inputs: RetrieveResult | RetrievedItem | list[RetrievedItem] | tuple[RetrievedItem, ...] | None = None,
    instructions: str | None = None,
    model: str | None = None,
    tools: list[str] | tuple[str, ...] | None = None,
    cache: str | dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> GenerationResult: ...

async def retrieve_history(
    *,
    scope: str = "session",
    session_id: str | None = None,
    limit: int | str = "all",
    message_filter: str = "all",
) -> RetrievedHistoryResult: ...

async def assemble_context(
    *,
    history: list[ContextMessage | HistoryMessage | ToolExchange | dict[str, Any] | str] | tuple[ContextMessage | HistoryMessage | ToolExchange | dict[str, Any] | str, ...] | None = None,
    context_messages: list[ContextMessage | HistoryMessage | ToolExchange | dict[str, Any] | str] | tuple[ContextMessage | HistoryMessage | ToolExchange | dict[str, Any] | str, ...] | None = None,
    instructions: str | None = None,
) -> AssembleContextResult: ...

async def parse_markdown(
    *,
    value: RetrievedItem | str,
) -> ParsedMarkdown: ...

async def finish(
    *,
    status: str = "completed",
    reason: str | None = None,
) -> FinishResult: ...

async def import_content(
    *,
    source: str,
    options: dict[str, Any] | None = None,
) -> Any: ...
