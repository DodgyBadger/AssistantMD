"""
Experiment scenario for the refactored memory_ops workstream contract.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings import EmbedInputType, EmbeddingModel, EmbeddingResult
from pydantic_ai.usage import RequestUsage

from core.memory.workstreams import WorkstreamStore
from core.tools.memory_ops import MemoryOps
from core.vector import VectorService
from validation.core.base_scenario import BaseScenario


class MemoryOpsWorkstreamProbeScenario(BaseScenario):
    """Probe memory_ops workstream operations without chat tool registration."""

    async def test_scenario(self):
        controller = self._get_system_controller()
        system_root = controller._system_root
        vault_name = "MemoryOpsProbeVault"

        store = WorkstreamStore(system_root=str(system_root))
        store.create_workstream(
            workstream_id="workstream-donor-wetlands",
            vault_name=vault_name,
            title="Wetlands donor report",
            type="donor report",
            topic="wetlands",
        )

        import core.tools.memory_ops as memory_ops_module

        original_vector_service = memory_ops_module.VectorService
        memory_ops_module.VectorService = lambda: VectorService(
            embedding_model_overrides={
                "embeddings": SemanticProbeEmbeddingModel(dimensions=1536)
            }
        )
        try:
            tool = MemoryOps.get_tool()
            ctx = SimpleNamespace(
                deps=SimpleNamespace(
                    session_id="riparian-grant-session",
                    vault_name=vault_name,
                    message_history=(),
                )
            )

            created = await _call(
                tool,
                ctx,
                operation="create_workstream",
                title="Riparian restoration grant",
                type="funding proposal",
                topic="riparian restoration",
                artifacts=[
                    {
                        "path": "Proposals/Riparian/grant.md",
                        "artifact_role": "planning_note",
                    }
                ],
            )
            created_id = created["workstream"]["workstream_id"]

            linked = await _call(
                tool,
                ctx,
                operation="link_session",
                workstream_id=created_id,
            )
            current = await _call(tool, ctx, operation="get_workstream")
            updated = await _call(
                tool,
                ctx,
                operation="update_workstream",
                workstream_id=created_id,
                strategy="reuse grant narrative",
            )
            searched = await _call(
                tool,
                ctx,
                operation="search_workstreams",
                field_type="topic",
                value="riparian restoration",
            )
            semantic_search = await _call(
                tool,
                ctx,
                operation="search_workstreams",
                field_type="topic",
                value="watershed protection",
            )
            fetched = await _call(
                tool,
                ctx,
                operation="get_workstream",
                workstream_id=created_id,
            )
            searched_by_type = await _call(
                tool,
                ctx,
                operation="search_workstreams",
                field_type="type",
                value="donor report",
            )
        finally:
            memory_ops_module.VectorService = original_vector_service

        report = {
            "created": created,
            "linked": linked,
            "current": current,
            "updated": updated,
            "searched": searched,
            "semantic_search": semantic_search,
            "fetched": fetched,
            "searched_by_type": searched_by_type,
        }
        (self.artifacts_dir / "memory_ops_workstream_probe.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.soft_assert_equal(created["status"], "ok", "create_workstream should succeed")
        self.soft_assert_equal(
            created["indexed_fields"],
            2,
            "create_workstream should index vector-searchable fields",
        )
        self.soft_assert_equal(linked["workstream"]["workstream_id"], created_id)
        self.soft_assert_equal(current["status"], "linked")
        self.soft_assert_equal(
            updated["indexed_fields"],
            3,
            "update_workstream should refresh vector-searchable fields",
        )
        self.soft_assert(
            updated["workstream"]["strategy"] == "reuse grant narrative",
            "update_workstream should replace direct strategy field",
        )
        self.soft_assert(
            any(workstream["workstream_id"] == created_id for workstream in searched["workstreams"]),
            "search_workstreams should find created topic",
        )
        self.soft_assert(
            any(
                match["workstream"]["workstream_id"] == created_id
                and match["match_type"] == "semantic"
                for match in semantic_search["matches"]
            ),
            "search_workstreams should use indexed field vectors for semantic matches",
        )
        self.soft_assert_equal(len(fetched["workstream"]["artifacts"]), 1)
        self.soft_assert(
            any(
                workstream["workstream_id"] == "workstream-donor-wetlands"
                for workstream in searched_by_type["workstreams"]
            ),
            "search_workstreams should retrieve candidates by field",
        )
        self.teardown_scenario()
        self.assert_no_failures()


async def _call(tool, ctx, **kwargs) -> dict:
    raw = await tool.function(ctx, **kwargs)
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


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
