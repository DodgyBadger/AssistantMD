"""Definition and execution for the read_cache(...) Monty helper."""

from __future__ import annotations

from core.authoring.contracts import (
    AuthoringCapabilityCall,
    AuthoringCapabilityDefinition,
    AuthoringExecutionContext,
    RetrievedItem,
)
from core.authoring.helpers.common import build_capability
from core.authoring.cache import get_cache_artifact, purge_expired_cache_artifacts
from core.logger import UnifiedLogger


logger = UnifiedLogger(tag="authoring-host")


def build_definition() -> AuthoringCapabilityDefinition:
    return build_capability(
        name="read_cache",
        doc="Read one cached artifact by cache ref inside constrained local code.",
        contract=_contract(),
        handler=execute,
    )


async def execute(
    call: AuthoringCapabilityCall,
    context: AuthoringExecutionContext,
) -> RetrievedItem:
    host = context.host
    ref = _parse_call(call)
    logger.add_sink("validation").info(
        "authoring_read_cache_started",
        data={
            "workflow_id": context.workflow_id,
            "ref": ref,
        },
    )

    purge_expired_cache_artifacts(now=host.reference_date)
    record = get_cache_artifact(
        owner_id=context.workflow_id,
        session_key=host.session_key,
        artifact_ref=ref,
        now=host.reference_date,
        week_start_day=host.week_start_day,
    )
    if record is None:
        result = RetrievedItem(ref=ref, content="", exists=False, metadata={})
    else:
        metadata = dict(record.get("metadata") or {})
        metadata.update(
            {
                "cache_mode": record.get("cache_mode"),
                "origin": record.get("origin"),
                "created_at": record.get("created_at"),
                "last_accessed_at": record.get("last_accessed_at"),
                "expires_at": record.get("expires_at"),
            }
        )
        result = RetrievedItem(
            ref=ref,
            content=str(record.get("raw_content") or ""),
            exists=True,
            metadata=metadata,
        )

    logger.add_sink("validation").info(
        "authoring_read_cache_completed",
        data={
            "workflow_id": context.workflow_id,
            "ref": ref,
            "exists": result.exists,
            "content_chars": len(result.content),
        },
    )
    return result


def _parse_call(call: AuthoringCapabilityCall) -> str:
    if call.args:
        raise ValueError("read_cache only supports keyword arguments")
    unknown = sorted(set(call.kwargs) - {"ref"})
    if unknown:
        raise ValueError(f"Unsupported read_cache arguments: {', '.join(unknown)}")
    ref = str(call.kwargs.get("ref") or "").strip()
    if not ref:
        raise ValueError("read_cache requires a non-empty 'ref'")
    return ref


def _contract() -> dict[str, object]:
    return {
        "signature": "read_cache(*, ref: str)",
        "summary": (
            "Read one cached artifact by cache ref inside constrained local code. "
            "Use this when chat reports that oversized tool output was stored in cache."
        ),
        "arguments": {
            "ref": {
                "type": "string",
                "required": True,
                "description": "Cache ref returned by chat for an oversized tool result.",
            }
        },
        "return_shape": {
            "ref": "Requested cache ref.",
            "content": "Cached content when present.",
            "exists": "Whether the cache artifact exists for the current chat session.",
            "metadata": "Stored cache metadata such as origin, cache mode, and timestamps.",
        },
        "examples": [
            {
                "code": (
                    'artifact = await read_cache(ref="tool/tavily_extract/call_abc123")\n'
                    "artifact.content[:2000]"
                ),
                "description": "Open one cached oversized tool result for local exploration.",
            }
        ],
    }
