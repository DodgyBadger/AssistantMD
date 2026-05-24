"""
Experiment scenario for the session_ops session operations contract.
"""

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from core.chat.chat_store import ChatStore
from core.memory.session_summary import SessionSummaryStore
from core.runtime.execution_tasks import chat_session_scope
from core.tools.session_ops import SessionOps
from core.vector import VectorService
from core.vault_state.service import VaultStateService
from validation.core.base_scenario import BaseScenario


class SessionOpsSessionProbeScenario(BaseScenario):
    """Probe session_ops session operations without chat tool registration."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        system_root = controller._system_root
        vault_name = "SessionOpsProbeVault"

        store = SessionSummaryStore(system_root=str(system_root))
        chat_store = ChatStore(system_root=str(system_root))
        VaultStateService()
        _insert_chat_mutation_rows(
            system_root=system_root,
            vault_id="session-ops-probe-vault-id",
            vault_name=vault_name,
            session_id="extract-session",
        )
        store.upsert_session_summary(
            session_id="session-donor-wetlands",
            vault_name=vault_name,
            title="Wetlands donor report",
            summary="Prepared a donor report about wetlands restoration.",
            domain="conservation fundraising",
            work_product="donor report",
            user_intent="Create a report for a donor about wetlands restoration work.",
            named_entities="North Star Foundation",
        )
        chat_store.add_messages(
            "extract-session",
            vault_name,
            [
                ModelRequest(
                    parts=[
                        UserPromptPart(
                            content="Help me draft a wetland restoration donor update."
                        )
                    ]
                ),
                ModelResponse(
                    parts=[
                        TextPart(
                            content="Here is a concise donor update about the wetlands work."
                        )
                    ]
                ),
            ],
        )
        chat_store.add_messages(
            "session-donor-wetlands",
            vault_name,
            [
                ModelRequest(parts=[UserPromptPart(content="Draft the wetlands donor report.")]),
            ],
        )
        chat_store.add_messages(
            "unsummarized-session",
            vault_name,
            [
                ModelRequest(parts=[UserPromptPart(content="A short unsummarized planning note.")]),
            ],
        )
        chat_store.add_tool_event(
            session_id="extract-session",
            vault_name=vault_name,
            tool_call_id="read-source-1",
            tool_name="file_ops_safe",
            event_type="call",
            args={"operation": "read", "path": "Sources/Wetlands/source-note.md"},
        )
        chat_store.add_tool_event(
            session_id="extract-session",
            vault_name=vault_name,
            tool_call_id="read-source-1",
            tool_name="file_ops_safe",
            event_type="result",
            result_text="Source note about wetland restoration progress and donor-facing outcomes.",
            result_metadata={"token_count": 9},
        )
        chat_store.add_tool_event(
            session_id="extract-session",
            vault_name=vault_name,
            tool_call_id="read-virtual-doc-1",
            tool_name="file_ops_safe",
            event_type="call",
            args={"operation": "read", "path": "__virtual_docs__/tools/delegate.md"},
        )
        chat_store.add_tool_event(
            session_id="extract-session",
            vault_name=vault_name,
            tool_call_id="read-virtual-doc-1",
            tool_name="file_ops_safe",
            event_type="result",
            result_text="Internal delegate tool documentation.",
            result_metadata={"token_count": 5},
        )

        import core.tools.session_ops as session_ops_module

        original_vector_service = session_ops_module.VectorService
        original_create_agent = session_ops_module.create_agent
        original_generate_response = session_ops_module.generate_response
        original_build_model_instance = session_ops_module.build_model_instance
        session_ops_module.VectorService = lambda: VectorService(
            embedding_model_overrides={
                "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
            }
        )

        async def _fake_create_agent(*, model, output_type):
            del model
            return output_type

        async def _fake_generate_response(agent, prompt):
            assert (
                "distilling what happened" in prompt
                or "turning a distilled AssistantMD chat-session summary" in prompt
                or "identifying the direct source materials" in prompt
            )
            if "distilling what happened" in prompt:
                self.soft_assert(
                    "You have been provided with:" in prompt,
                    "summary/intent prompt should describe its inputs",
                )
                self.soft_assert(
                    "Target 500-800 characters" in prompt
                    and "never exceed 1,000 characters" in prompt
                    and "never exceed 500 characters" in prompt,
                    "summary/intent prompt should include field length contracts",
                )
                self.soft_assert(
                    "do not preserve a full" in prompt and "process log" in prompt,
                    "summary prompt should prefer compact retrieval-card output",
                )
            if "turning a distilled AssistantMD chat-session summary" in prompt:
                self.soft_assert(
                    "Create concise labels" in prompt,
                    "classification prompt should frame labels as retrieval aids",
                )
            if "identifying the direct source materials" in prompt:
                self.soft_assert(
                    "__virtual_docs__" not in prompt,
                    "source_summary tool log should filter virtual docs file reads",
                )
                self.soft_assert(
                    "Do not create bullets named `Session summary`, `Tool log`" in prompt,
                    "source_summary prompt should forbid meta-source labels",
                )
            if agent is session_ops_module._SessionSummaryIntent:
                return session_ops_module._SessionSummaryIntent(
                    summary="Drafted a donor update about wetland restoration.",
                    user_intent="Prepare a donor-facing update about wetland restoration progress.",
                )
            if agent is session_ops_module._SessionClassification:
                return session_ops_module._SessionClassification(
                    domain="conservation fundraising",
                    work_product="donor update",
                    named_entities="",
                )
            return session_ops_module._SessionSourceSummary(
                source_summary="Read Sources/Wetlands/source-note.md for wetland restoration progress and donor-facing outcomes.",
            )

        session_ops_module.create_agent = _fake_create_agent
        session_ops_module.generate_response = _fake_generate_response
        session_ops_module.build_model_instance = lambda value: value
        try:
            await store.index_session_summary_fields(
                vault_name=vault_name,
                session_id="session-donor-wetlands",
                vector_service=session_ops_module.VectorService(),
            )
            tool = SessionOps.get_tool()
            ctx = SimpleNamespace(
                deps=SimpleNamespace(
                    session_id="riparian-grant-session",
                    vault_name=vault_name,
                    message_history=(),
                )
            )
            extract_ctx = SimpleNamespace(
                deps=SimpleNamespace(
                    session_id="extract-session",
                    vault_name=vault_name,
                    message_history=(),
                )
            )

            extracted = await _call(
                tool,
                extract_ctx,
                operation="summarize_session",
            )

            upserted = await _call(
                tool,
                ctx,
                operation="upsert_session_summary",
                data={
                    "summary": "Drafting a grant proposal about riparian restoration.",
                    "domain": "conservation fundraising",
                    "work_product": "funding proposal",
                    "user_intent": "Create a funding proposal for riparian restoration work.",
                    "named_entities": "Riparian Funders Network",
                    "source_summary": "Read prior riparian proposal notes.",
                    "artifacts": [
                        {
                            "path": "Proposals/Riparian/grant.md",
                            "artifact_role": "planning_note",
                        }
                    ],
                    "metadata": {"source": "validation_probe"},
                },
            )

            current = await _call(tool, ctx, operation="get_session_summary")
            updated = await _call(
                tool,
                ctx,
                operation="upsert_session_summary",
                data={
                    "summary": "Drafting a grant proposal about riparian restoration using a reusable grant narrative.",
                    "domain": "conservation fundraising",
                    "work_product": "funding proposal",
                    "user_intent": "Create a funding proposal for riparian restoration work.",
                },
            )
            cleared = await _call(
                tool,
                ctx,
                operation="upsert_session_summary",
                data={
                    "named_entities": None,
                    "source_summary": "",
                },
            )
            listed = await _call(
                tool,
                ctx,
                operation="list_sessions",
                limit=2,
            )
            listed_next = await _call(
                tool,
                ctx,
                operation="list_sessions",
                limit=2,
                cursor=listed.get("next_cursor") or "",
            )
            listed_pending = await _call(
                tool,
                ctx,
                operation="list_sessions",
                summary_status="pending",
                limit=10,
            )
            searched = await _call(
                tool,
                ctx,
                operation="search_sessions",
                query="riparian restoration",
            )
            semantic_search = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query="watershed protection",
            )
            fetched = await _call(
                tool,
                ctx,
                operation="get_session_summary",
            )
            searched_by_type = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query="donor report",
            )
            boolean_search_error = await _call_model_retry(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query='GHG OR "greenhouse gas"',
                limit=5,
            )
            natural_language_search = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query="riparian restoration and watershed protection",
                limit=5,
            )
            all_limit_error = await _call_model_retry(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query="greenhouse gas GHG",
                limit="all",
            )
            no_query_search_error = await _call_model_retry(
                tool,
                ctx,
                operation="search_sessions",
            )
            related = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="related",
            )
        finally:
            session_ops_module.VectorService = original_vector_service
            session_ops_module.create_agent = original_create_agent
            session_ops_module.generate_response = original_generate_response
            session_ops_module.build_model_instance = original_build_model_instance

        report = {
            "extracted": extracted,
            "upserted": upserted,
            "current": current,
            "updated": updated,
            "cleared": cleared,
            "listed": listed,
            "listed_next": listed_next,
            "listed_pending": listed_pending,
            "searched": searched,
            "semantic_search": semantic_search,
            "fetched": fetched,
            "searched_by_type": searched_by_type,
            "boolean_search_error": boolean_search_error,
            "natural_language_search": natural_language_search,
            "all_limit_error": all_limit_error,
            "no_query_search_error": no_query_search_error,
            "related": related,
        }
        (self.artifacts_dir / "session_ops_session_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(upserted["status"], "ok", "upsert_session_summary should succeed")
        self.soft_assert_equal(
            extracted["status"],
            "ok",
            "summarize_session should succeed",
        )
        self.soft_assert_equal(
            extracted["session_summary"]["session_id"],
            "extract-session",
            "summarize_session should store a summary for the active session",
        )
        self.soft_assert_equal(
            extracted["session_summary"]["summary"],
            "Drafted a donor update about wetland restoration.",
            "summarize_session should persist extracted summary",
        )
        self.soft_assert_equal(
            extracted["indexed_fields"],
            4,
            "summarize_session should index extracted vector-searchable fields",
        )
        self.soft_assert_equal(
            extracted["session_summary"]["source_summary"],
            "Read Sources/Wetlands/source-note.md for wetland restoration progress and donor-facing outcomes.",
            "summarize_session should persist source_summary from tool events",
        )
        self.soft_assert_equal(
            extracted["artifact_count"],
            2,
            "summarize_session should attach artifacts from chat-scoped file mutations",
        )
        extracted_artifacts = extracted["session_summary"]["artifacts"]
        self.soft_assert_equal(
            {artifact["path"] for artifact in extracted_artifacts},
            {"Reports/Wetlands/update.md", "Reports/Wetlands/archive.md"},
            "Extracted memory artifacts should include mutated vault paths",
        )
        self.soft_assert_equal(
            {
                (artifact["path"], artifact["artifact_role"])
                for artifact in extracted_artifacts
            },
            {
                ("Reports/Wetlands/update.md", "created"),
                ("Reports/Wetlands/archive.md", "deleted"),
            },
            "Extracted memory artifacts should classify simple create/delete mutations",
        )
        self.soft_assert_equal(
            upserted["indexed_fields"],
            4,
            "upsert_session_summary should index vector-searchable fields",
        )
        self.soft_assert_equal(current["status"], "found")
        self.soft_assert_equal(
            current["session_summary"]["session_id"],
            "riparian-grant-session",
        )
        self.soft_assert_equal(
            updated["indexed_fields"],
            4,
            "upsert_session_summary should refresh vector-searchable fields",
        )
        self.soft_assert(
            updated["session_summary"]["summary"]
            == "Drafting a grant proposal about riparian restoration using a reusable grant narrative.",
            "upsert_session_summary should replace direct summary field",
        )
        self.soft_assert_equal(
            updated["session_summary"]["named_entities"],
            "Riparian Funders Network",
            "upsert_session_summary should preserve omitted fields",
        )
        self.soft_assert_equal(
            updated["session_summary"]["source_summary"],
            "Read prior riparian proposal notes.",
            "upsert_session_summary should preserve omitted provenance",
        )
        self.soft_assert_equal(
            cleared["session_summary"]["summary"],
            "Drafting a grant proposal about riparian restoration using a reusable grant narrative.",
            "upsert_session_summary should preserve omitted vector fields during targeted clears",
        )
        self.soft_assert_equal(
            cleared["session_summary"]["named_entities"],
            None,
            "upsert_session_summary should clear explicit null fields",
        )
        self.soft_assert_equal(
            cleared["session_summary"]["source_summary"],
            None,
            "upsert_session_summary should clear stale provenance when empty",
        )
        self.soft_assert_equal(
            listed["status"],
            "ok",
            "list_sessions should succeed",
        )
        self.soft_assert_equal(
            listed["total_count"],
            3,
            "list_sessions should default to summarized sessions",
        )
        self.soft_assert_equal(
            listed["returned_count"],
            2,
            "list_sessions should return one compact page",
        )
        self.soft_assert(
            listed["next_cursor"] is not None,
            "list_sessions should provide a cursor when more rows exist",
        )
        self.soft_assert_equal(
            len(listed["sessions"] + listed_next["sessions"]),
            3,
            "list_sessions cursor should page through the full compact listing",
        )
        self.soft_assert(
            all(item["has_summary"] for item in listed["sessions"]),
            "list_sessions should only return summarized sessions by default",
        )
        self.soft_assert(
            all("summary" not in item for item in listed["sessions"]),
            "list_sessions should not return full summaries",
        )
        self.soft_assert(
            any(item["session_id"] == "unsummarized-session" for item in listed_pending["sessions"]),
            "list_sessions should support pending summary exploration",
        )
        self.soft_assert(
            any(
                match["session_id"] == "riparian-grant-session"
                for match in searched["matches"]
            ),
            "search_sessions should find created session summary",
        )
        self.soft_assert(
            any(
                match["session_id"] == "riparian-grant-session"
                and any(
                    evidence["match_type"] == "semantic"
                    for evidence in match["evidence"]
                )
                for match in semantic_search["matches"]
            ),
            "search_sessions should use indexed field vectors for semantic matches",
        )
        self.soft_assert_equal(len(fetched["session_summary"]["artifacts"]), 1)
        self.soft_assert(
            any(
                match["session_id"] == "session-donor-wetlands"
                for match in searched_by_type["matches"]
            ),
            "search_sessions should retrieve candidates across session-summary fields",
        )
        self.soft_assert(
            "plain search phrase" in boolean_search_error,
            "Boolean-looking search queries should trigger a retryable correction",
        )
        self.soft_assert_equal(
            natural_language_search["status"],
            "ok",
            "Natural-language search queries containing lowercase conjunctions should be accepted",
        )
        self.soft_assert(
            "positive integer limit" in all_limit_error,
            "search_sessions should reject limit='all' with a retryable correction",
        )
        self.soft_assert(
            "plain natural-language query" in no_query_search_error,
            "default search mode should require a query",
        )
        self.soft_assert_equal(related["status"], "ok")
        self.soft_assert(
            "session_summaries" not in related,
            "related search should expose matches as the canonical result list",
        )
        self.soft_assert(
            all(
                match["session_summary"]["session_id"] != "riparian-grant-session"
                for match in related["matches"]
            ),
            "related search should exclude the current session",
        )
        self.soft_assert(
            any(
                match["session_summary"]["session_id"] == "session-donor-wetlands"
                for match in related["matches"]
            ),
            "related search should retrieve related prior sessions",
        )
        self.soft_assert(
            all(match["contributions"] for match in related["matches"]),
            "related search should explain field contributions",
        )
        self.teardown_scenario()
        self.assert_no_failures()


async def _call(tool, ctx, **kwargs) -> dict:
    raw = await tool.function(ctx, **kwargs)
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


async def _call_model_retry(tool, ctx, **kwargs) -> str:
    try:
        await tool.function(ctx, **kwargs)
    except ModelRetry as exc:
        return str(exc)
    raise AssertionError("Expected session_ops call to raise ModelRetry")


def _insert_chat_mutation_rows(
    *,
    system_root: Path,
    vault_id: str,
    vault_name: str,
    session_id: str,
) -> None:
    db_path = system_root / "vault_state.db"
    now = datetime.now(UTC)
    rows = [
        (
            "memory-extract-chat-task-1",
            "chat",
            "api",
            chat_session_scope(session_id),
            f"chat:{session_id}",
            vault_id,
            vault_name,
            "Reports/Wetlands/update.md",
            None,
            "write",
            101,
            0,
            None,
            None,
            1,
            "created-hash",
            None,
            None,
            now.isoformat(),
            (now + timedelta(days=7)).isoformat(),
        ),
        (
            "memory-extract-chat-task-2",
            "chat",
            "api",
            chat_session_scope(session_id),
            f"chat:{session_id}",
            vault_id,
            vault_name,
            "Reports/Wetlands/archive.md",
            None,
            "delete",
            102,
            1,
            "deleted-before-hash",
            None,
            0,
            None,
            None,
            None,
            (now + timedelta(seconds=1)).isoformat(),
            (now + timedelta(days=7)).isoformat(),
        ),
    ]
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO task_file_mutations (
                task_id, task_kind, task_source, task_scope, task_label,
                vault_id, vault_name, path, related_path, operation,
                event_sequence, before_exists, before_hash, before_snapshot_id,
                after_exists, after_hash, after_snapshot_id, snapshot_ref,
                created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class SemanticProbeEmbeddingModel(EmbeddingModel):
    """Deterministic semantic embedding model for this validation scenario."""

    def __init__(self, *, dimensions: int = 1536):
        self._dimensions = dimensions
        super().__init__()

    @property
    def model_name(self) -> str:
        return "semantic-probe"

    @property
    def system(self) -> str:
        return "test"

    async def embed(
        self,
        inputs: str | Sequence[str],
        *,
        input_type: EmbedInputType,
        settings: dict[str, Any] | None = None,
    ) -> EmbeddingResult:
        input_list, merged_settings = self.prepare_embed(inputs, settings)
        dimensions = int(merged_settings.get("dimensions") or self._dimensions)
        return EmbeddingResult(
            embeddings=[_semantic_probe_vector(text, dimensions) for text in input_list],
            inputs=input_list,
            input_type=input_type,
            model_name=self.model_name,
            provider_name=self.system,
            usage=RequestUsage(input_tokens=sum(len(text.split()) for text in input_list)),
        )


def _semantic_probe_vector(text: str, dimensions: int) -> list[float]:
    lowered = text.lower()
    if "wetland" in lowered:
        base = (0.96, 0.18, 0.08, 0.0)
    elif "riparian" in lowered:
        base = (0.9, 0.28, 0.14, 0.0)
    elif "watershed" in lowered:
        base = (0.86, 0.34, 0.18, 0.0)
    elif "conservation" in lowered:
        base = (0.88, 0.32, 0.16, 0.0)
    elif "forest" in lowered:
        base = (0.18, 0.94, 0.08, 0.0)
    elif "donor report" in lowered:
        base = (0.1, 0.0, 0.18, 0.92)
    elif "funding proposal" in lowered or "grant proposal" in lowered:
        base = (0.16, 0.0, 0.12, 0.86)
    else:
        base = (0.01, 0.01, 0.01, 0.01)
    vector = list(base[:dimensions])
    if len(vector) < dimensions:
        vector.extend([0.0] * (dimensions - len(vector)))
    return vector
