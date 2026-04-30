"""Definition and execution for the parse_markdown(...) Monty helper."""

from __future__ import annotations

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    ParsedMarkdown,
    RetrievedItem,
)
from core.authoring.helpers.common import build_capability
from core.authoring.shared.markdown_parse import parse_markdown_content
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="parse_markdown",
        doc=(
            "Parse markdown content into frontmatter, body, headings, sections, "
            "code blocks, and image references for structured exploration."
        ),
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> ParsedMarkdown:
    source = _parse_source(call)
    logger.add_sink("validation").info(
        "authoring_parse_markdown_started",
        data={
            "workflow_id": context.workflow_id,
            "source_type": type(source).__name__,
        },
    )
    parsed = parse_markdown_content(source)
    logger.add_sink("validation").info(
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


def _parse_source(call: AuthoringCapabilityCall) -> str:
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


def _contract() -> dict[str, object]:
    return {
        "signature": "parse_markdown(*, value: RetrievedItem | str)",
        "summary": (
            "Parse markdown content into a stable structured object. Accepts either a "
            "RetrievedItem from retrieve(type=\"file\", ...) or a raw markdown string."
        ),
        "arguments": {
            "value": {
                "type": "RetrievedItem | string",
                "required": True,
                "description": (
                    "Markdown source to parse. When a RetrievedItem is provided, its content "
                    "field is parsed directly."
                ),
            },
        },
        "return_shape": {
            "frontmatter": "Parsed flat frontmatter key/value mapping.",
            "body": "Document body with frontmatter removed.",
            "headings": [
                {
                    "level": "Heading depth such as 1 for # and 2 for ##.",
                    "text": "Heading text.",
                    "line_start": "1-based line number in the body where the heading starts.",
                }
            ],
            "sections": [
                {
                    "heading": "Heading text for the section.",
                    "level": "Heading depth for the section heading.",
                    "content": "Body content that belongs to the section.",
                    "line_start": "1-based line number in the body where the section heading starts.",
                }
            ],
            "code_blocks": [
                {
                    "language": "Fence language when present, otherwise null.",
                    "content": "Fenced code block body.",
                    "line_start": "1-based line number where the code block starts when available.",
                }
            ],
            "images": [
                {
                    "src": "Image source path or URL from markdown.",
                    "alt": "Alt text from the markdown image.",
                    "title": "Optional title attribute when present.",
                    "line_start": "1-based line number where the image was discovered when available.",
                }
            ],
        },
        "notes": [
            (
                "Use parse_markdown(...) for structural discovery and common extraction. "
                "Use normal Python to select or combine the parsed pieces you care about."
            )
        ],
        "examples": [
            {
                "code": (
                    'note = (await retrieve(type="file", ref="notes/reference.md")).items[0]\n'
                    "parsed = await parse_markdown(value=note)\n"
                    "titles = [heading.text for heading in parsed.headings]"
                ),
                "description": "Inspect the top-level structure of a retrieved markdown file.",
            },
            {
                "code": (
                    'skill = (await retrieve(type="file", ref="Skills/example.md")).items[0]\n'
                    "parsed = await parse_markdown(value=skill)\n"
                    'name = parsed.frontmatter.get("name")\n'
                    'description = parsed.frontmatter.get("description")'
                ),
                "description": "Extract frontmatter fields from a retrieved markdown file.",
            },
            {
                "code": (
                    "parsed = await parse_markdown(value=markdown_text)\n"
                    'target = next((section for section in parsed.sections if section.heading == "AI In Fiction"), None)'
                ),
                "description": "Parse raw markdown text and select one section in ordinary Python.",
            },
        ],
    }
