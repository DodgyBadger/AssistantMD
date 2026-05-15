"""
Experiment scenario for shared embedding/vector service plumbing.

This uses Pydantic AI's TestEmbeddingModel and does not make provider calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic_ai.embeddings.test import TestEmbeddingModel

from core.settings.config_editor import upsert_model_mapping
from core.vector import (
    SQLitePythonVectorStore,
    VectorService,
    build_embedding_space_id,
    cosine_similarity,
)
from validation.core.base_scenario import BaseScenario


class VectorEmbeddingServiceProbeScenario(BaseScenario):
    """Probe settings-backed embedding service behavior."""

    async def test_scenario(self):
        self._get_system_controller()
        upsert_model_mapping(
            name="embeddings",
            provider="openai",
            model_string="text-embedding-3-small",
            capabilities=["embedding"],
            dimensions=1536,
            description="Validation embedding model alias",
        )
        upsert_model_mapping(
            name="embeddings-512",
            provider="openai",
            model_string="text-embedding-3-small",
            capabilities=["embedding"],
            dimensions=512,
            description="Validation incompatible embedding model alias",
        )

        service = VectorService(
            embedding_model_overrides={
                "embeddings": TestEmbeddingModel(
                    model_name="test-embedding",
                    provider_name="test",
                    dimensions=1536,
                ),
                "embeddings-512": TestEmbeddingModel(
                    model_name="test-embedding",
                    provider_name="test",
                    dimensions=512,
                ),
            }
        )

        query = await service.embed_query("riparian restoration", model_alias="embeddings")
        documents = await service.embed_documents(
            ["topic: wetlands", "topic: watershed protection"],
            model_alias="embeddings",
        )
        other_space_query = await service.embed_query(
            "topic: wetlands",
            model_alias="embeddings-512",
        )

        self.soft_assert_equal(
            len(query.vectors[0].vector),
            1536,
            "Query vector should use configured embedding dimensions",
        )
        self.soft_assert_equal(
            len(documents.vectors),
            2,
            "Document embedding should return one vector per input",
        )
        self.soft_assert_equal(
            query.embedding_space_id,
            documents.embedding_space_id,
            "Query and document vectors from the same alias should share embedding space",
        )
        self.soft_assert_equal(
            query.embedding_space_id,
            build_embedding_space_id(
                provider="openai",
                base_url=None,
                model_string="text-embedding-3-small",
                dimensions=1536,
            ),
            "Embedding space should derive from provider/base URL/model/dimensions",
        )
        self.soft_assert(
            cosine_similarity(query.vectors[0].vector, documents.vectors[0].vector) > 0,
            "Cosine similarity should work for same-dimension vectors",
        )

        try:
            cosine_similarity((1.0, 2.0), (1.0,))
        except ValueError as exc:
            self.soft_assert(
                "different dimensions" in str(exc),
                "Dimension mismatch error should explain incompatible vectors",
            )
        else:
            self.soft_assert(False, "Dimension mismatch should raise ValueError")

        vector_store = SQLitePythonVectorStore(
            db_name="memory",
            table_name="validation_vectors",
        )
        vector_store.upsert(
            namespace="session_memory_fields",
            item_id="session-wetlands:domain",
            embedding=documents.vectors[0],
        )
        vector_store.upsert(
            namespace="session_memory_fields",
            item_id="session-watershed:domain",
            embedding=documents.vectors[1],
        )
        vector_store.upsert(
            namespace="session_memory_fields",
            item_id="session-other-space:domain",
            embedding=other_space_query.vectors[0],
        )
        results = vector_store.search_similar(
            namespace="session_memory_fields",
            query=query.vectors[0],
            limit=5,
        )
        self.soft_assert_equal(
            len(results),
            2,
            "Vector store should search only within the query embedding space",
        )
        self.soft_assert(
            all(result.embedding_space_id == query.embedding_space_id for result in results),
            "Vector search results should all share query embedding space",
        )

        self.teardown_scenario()
        self.assert_no_failures()
