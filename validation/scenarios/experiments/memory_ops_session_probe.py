"""
Experiment scenario for the memory_ops session memory contract.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from core.chat.chat_store import ChatStore
from core.memory.session_memory import SessionMemoryStore
from core.tools.memory_ops import MemoryOps
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


class MemoryOpsSessionProbeScenario(BaseScenario):
    """Probe memory_ops session memory operations without chat tool registration."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        system_root = controller._system_root
        vault_name = "MemoryOpsProbeVault"

        store = SessionMemoryStore(system_root=str(system_root))
        chat_store = ChatStore(system_root=str(system_root))
        store.upsert_session_memory(
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

        import core.tools.memory_ops as memory_ops_module

        original_vector_service = memory_ops_module.VectorService
        original_create_agent = memory_ops_module.create_agent
        original_generate_response = memory_ops_module.generate_response
        original_build_model_instance = memory_ops_module.build_model_instance
        memory_ops_module.VectorService = lambda: VectorService(
            embedding_model_overrides={
                "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
            }
        )

        async def _fake_create_agent(*, model, output_type):
            del model
            return output_type

        async def _fake_generate_response(agent, prompt):
            assert "extract only" in prompt or "Extract classification fields" in prompt
            if agent is memory_ops_module._SessionSummaryIntent:
                return memory_ops_module._SessionSummaryIntent(
                    summary="Drafted a donor update about wetland restoration.",
                    user_intent="Prepare a donor-facing update about wetland restoration progress.",
                )
            return memory_ops_module._SessionClassification(
                domain="conservation fundraising",
                work_product="donor update",
                named_entities="",
            )

        memory_ops_module.create_agent = _fake_create_agent
        memory_ops_module.generate_response = _fake_generate_response
        memory_ops_module.build_model_instance = lambda value: value
        try:
            await store.index_session_memory_fields(
                vault_name=vault_name,
                session_id="session-donor-wetlands",
                vector_service=memory_ops_module.VectorService(),
            )
            tool = MemoryOps.get_tool()
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
                operation="extract_session_memory",
            )

            upserted = await _call(
                tool,
                ctx,
                operation="upsert_session_memory",
                title="Riparian restoration grant",
                summary="Drafting a grant proposal about riparian restoration.",
                domain="conservation fundraising",
                work_product="funding proposal",
                user_intent="Create a funding proposal for riparian restoration work.",
                artifacts=[
                    {
                        "path": "Proposals/Riparian/grant.md",
                        "artifact_role": "planning_note",
                    }
                ],
            )

            current = await _call(tool, ctx, operation="get_session_memory")
            updated = await _call(
                tool,
                ctx,
                operation="upsert_session_memory",
                summary="Drafting a grant proposal about riparian restoration using a reusable grant narrative.",
                domain="conservation fundraising",
                work_product="funding proposal",
                user_intent="Create a funding proposal for riparian restoration work.",
            )
            searched = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
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
                operation="get_session_memory",
            )
            searched_by_type = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="search",
                query="donor report",
            )
            legacy_field_search = await _call(
                tool,
                ctx,
                operation="search_sessions",
                field_type="summary",
                value="riparian",
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
            related = await _call(
                tool,
                ctx,
                operation="search_sessions",
            )
            related_with_ignored_fields = await _call(
                tool,
                ctx,
                operation="search_sessions",
                mode="related",
                domain="unrelated cooking",
                work_product="recipe",
                user_intent="Find dinner ideas.",
            )
        finally:
            memory_ops_module.VectorService = original_vector_service
            memory_ops_module.create_agent = original_create_agent
            memory_ops_module.generate_response = original_generate_response
            memory_ops_module.build_model_instance = original_build_model_instance

        report = {
            "extracted": extracted,
            "upserted": upserted,
            "current": current,
            "updated": updated,
            "searched": searched,
            "semantic_search": semantic_search,
            "fetched": fetched,
            "searched_by_type": searched_by_type,
            "legacy_field_search": legacy_field_search,
            "boolean_search_error": boolean_search_error,
            "natural_language_search": natural_language_search,
            "all_limit_error": all_limit_error,
            "related": related,
            "related_with_ignored_fields": related_with_ignored_fields,
        }
        (self.artifacts_dir / "memory_ops_session_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(upserted["status"], "ok", "upsert_session_memory should succeed")
        self.soft_assert_equal(
            extracted["status"],
            "ok",
            "extract_session_memory should succeed",
        )
        self.soft_assert_equal(
            extracted["session_memory"]["session_id"],
            "extract-session",
            "extract_session_memory should store memory for the active session",
        )
        self.soft_assert_equal(
            extracted["session_memory"]["summary"],
            "Drafted a donor update about wetland restoration.",
            "extract_session_memory should persist extracted summary",
        )
        self.soft_assert_equal(
            extracted["indexed_fields"],
            4,
            "extract_session_memory should index extracted vector-searchable fields",
        )
        self.soft_assert_equal(
            upserted["indexed_fields"],
            4,
            "upsert_session_memory should index vector-searchable fields",
        )
        self.soft_assert_equal(current["status"], "found")
        self.soft_assert_equal(
            current["session_memory"]["session_id"],
            "riparian-grant-session",
        )
        self.soft_assert_equal(
            updated["indexed_fields"],
            4,
            "upsert_session_memory should refresh vector-searchable fields",
        )
        self.soft_assert(
            updated["session_memory"]["summary"]
            == "Drafting a grant proposal about riparian restoration using a reusable grant narrative.",
            "upsert_session_memory should replace direct summary field",
        )
        self.soft_assert(
            any(
                match["session_id"] == "riparian-grant-session"
                for match in searched["matches"]
            ),
            "search_sessions should find created session memory",
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
        self.soft_assert_equal(len(fetched["session_memory"]["artifacts"]), 1)
        self.soft_assert(
            any(
                match["session_id"] == "session-donor-wetlands"
                for match in searched_by_type["matches"]
            ),
            "search_sessions should retrieve candidates across memory fields",
        )
        self.soft_assert_equal(
            legacy_field_search["mode"],
            "search",
            "legacy field/value calls should be translated to search mode",
        )
        self.soft_assert(
            any(
                match["session_id"] == "riparian-grant-session"
                for match in legacy_field_search["matches"]
            ),
            "legacy field/value calls should not fail tool validation",
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
        self.soft_assert_equal(related["status"], "ok")
        self.soft_assert(
            all(
                match["session_memory"]["session_id"] != "riparian-grant-session"
                for match in related["matches"]
            ),
            "related search should exclude the current session",
        )
        self.soft_assert(
            any(
                match["session_memory"]["session_id"] == "session-donor-wetlands"
                for match in related["matches"]
            ),
            "related search should retrieve related prior sessions",
        )
        self.soft_assert(
            all(match["contributions"] for match in related["matches"]),
            "related search should explain field contributions",
        )
        self.soft_assert_equal(
            related_with_ignored_fields["matches"],
            related["matches"],
            "related search should ignore caller-supplied field overrides",
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
    raise AssertionError("Expected memory_ops call to raise ModelRetry")


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
