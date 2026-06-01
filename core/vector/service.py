"""Provider-neutral embedding service backed by Pydantic AI."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal, Sequence

from pydantic_ai import Embedder
from pydantic_ai.embeddings import EmbeddingModel
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.embeddings.test import TestEmbeddingModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.settings.secrets_store import get_secret_value
from core.settings.store import ModelConfig, get_models_config, get_providers_config


EmbeddingInputType = Literal["query", "document"]


@dataclass(frozen=True)
class EmbeddingVector:
    """One embedding vector with vector-space metadata."""

    text: str
    vector: tuple[float, ...]
    input_type: EmbeddingInputType
    model_alias: str
    provider: str
    model_string: str
    dimensions: int
    embedding_space_id: str
    provider_name: str
    model_name: str


@dataclass(frozen=True)
class EmbeddingRequestResult:
    """Embedding request result normalized for AssistantMD consumers."""

    vectors: tuple[EmbeddingVector, ...]
    model_alias: str
    provider: str
    model_string: str
    dimensions: int
    embedding_space_id: str
    usage: dict[str, object]


class VectorService:
    """Build and run embedding requests from settings-backed model aliases."""

    def __init__(
        self,
        *,
        embedding_model_overrides: dict[str, EmbeddingModel] | None = None,
    ):
        self.embedding_model_overrides = embedding_model_overrides or {}

    async def embed_query(
        self,
        text: str,
        *,
        model_alias: str = "embeddings",
    ) -> EmbeddingRequestResult:
        """Embed one query string."""
        return await self._embed([text], input_type="query", model_alias=model_alias)

    async def embed_documents(
        self,
        texts: Sequence[str],
        *,
        model_alias: str = "embeddings",
    ) -> EmbeddingRequestResult:
        """Embed one or more document strings."""
        return await self._embed(list(texts), input_type="document", model_alias=model_alias)

    async def _embed(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInputType,
        model_alias: str,
    ) -> EmbeddingRequestResult:
        if not texts:
            raise ValueError("Embedding input cannot be empty")
        resolved = resolve_embedding_model_config(model_alias)
        embedder = Embedder(self._build_embedding_model(resolved))
        settings = {"dimensions": resolved.dimensions}
        if input_type == "query":
            result = await embedder.embed_query(texts, settings=settings)
        else:
            result = await embedder.embed_documents(texts, settings=settings)

        vectors: list[EmbeddingVector] = []
        for text, vector in zip(result.inputs, result.embeddings, strict=True):
            vector_tuple = tuple(float(value) for value in vector)
            if len(vector_tuple) != resolved.dimensions:
                raise ValueError(
                    "Embedding provider returned an unexpected dimension count: "
                    f"expected {resolved.dimensions}, got {len(vector_tuple)}"
                )
            vectors.append(
                EmbeddingVector(
                    text=text,
                    vector=vector_tuple,
                    input_type=input_type,
                    model_alias=resolved.alias,
                    provider=resolved.provider,
                    model_string=resolved.model_string,
                    dimensions=resolved.dimensions,
                    embedding_space_id=resolved.embedding_space_id,
                    provider_name=result.provider_name,
                    model_name=result.model_name,
                )
            )

        return EmbeddingRequestResult(
            vectors=tuple(vectors),
            model_alias=resolved.alias,
            provider=resolved.provider,
            model_string=resolved.model_string,
            dimensions=resolved.dimensions,
            embedding_space_id=resolved.embedding_space_id,
            usage=_usage_to_dict(result.usage),
        )

    def _build_embedding_model(self, config: "ResolvedEmbeddingModelConfig") -> EmbeddingModel:
        override = self.embedding_model_overrides.get(config.alias)
        if override is not None:
            return override
        if config.provider == "test":
            return TestEmbeddingModel(dimensions=config.dimensions)
        return OpenAIEmbeddingModel(
            config.model_string,
            provider=OpenAIProvider(api_key=config.api_key, base_url=config.base_url),
        )


@dataclass(frozen=True)
class ResolvedEmbeddingModelConfig:
    """Resolved settings needed to construct an embedding model."""

    alias: str
    provider: str
    model_string: str
    dimensions: int
    base_url: str | None
    api_key: str | None
    embedding_space_id: str


def resolve_embedding_model_config(model_alias: str) -> ResolvedEmbeddingModelConfig:
    """Resolve an embedding model alias using existing model/provider settings."""
    alias = model_alias.strip().lower()
    if not alias:
        raise ValueError("Embedding model alias cannot be empty")

    models = get_models_config()
    model = models.get(alias)
    if model is None:
        available = ", ".join(sorted(models))
        raise ValueError(f"Unknown embedding model alias '{model_alias}'. Available: {available}")

    capabilities = set(_model_capabilities(model))
    if "embedding" not in capabilities:
        raise ValueError(f"Model alias '{model_alias}' does not declare embedding capability")

    dimensions = getattr(model, "dimensions", None)
    if dimensions is None:
        raise ValueError(f"Embedding model alias '{model_alias}' must declare dimensions")
    if int(dimensions) <= 0:
        raise ValueError(f"Embedding model alias '{model_alias}' dimensions must be positive")

    providers = get_providers_config()
    provider_name = str(model.provider).strip()
    provider = providers.get(provider_name)
    if provider is None:
        raise ValueError(
            f"Embedding model alias '{model_alias}' references unknown provider '{provider_name}'"
        )

    base_url = _resolve_provider_value(provider.base_url)
    api_key = _resolve_provider_value(provider.api_key)
    if provider_name not in {"openai", "test"} and not base_url:
        raise ValueError(
            f"Embedding provider '{provider_name}' requires base_url for OpenAI-compatible use"
        )

    return ResolvedEmbeddingModelConfig(
        alias=alias,
        provider=provider_name,
        model_string=model.model_string,
        dimensions=int(dimensions),
        base_url=base_url,
        api_key=api_key,
        embedding_space_id=build_embedding_space_id(
            provider=provider_name,
            base_url=base_url,
            model_string=model.model_string,
            dimensions=int(dimensions),
        ),
    )


def build_embedding_space_id(
    *,
    provider: str,
    base_url: str | None,
    model_string: str,
    dimensions: int,
) -> str:
    """Build a stable id for vectors that are safe to compare."""
    raw = "\n".join(
        [
            provider.strip().lower(),
            (base_url or "").strip().rstrip("/"),
            model_string.strip(),
            str(dimensions),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"embspace:{digest}"


def fingerprint_text(text: str) -> str:
    """Return a stable fingerprint for embedding input text."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity for vectors in the same embedding space."""
    if len(left) != len(right):
        raise ValueError(
            f"Cannot compare vectors with different dimensions: {len(left)} != {len(right)}"
        )
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0
    return numerator / (left_norm * right_norm)


def _model_capabilities(model: ModelConfig) -> list[str]:
    return [str(capability).strip().lower() for capability in model.capabilities]


def _resolve_provider_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value or value.lower() == "null":
        return None
    return get_secret_value(value) or value


def _usage_to_dict(usage: object) -> dict[str, object]:
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    data: dict[str, object] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "requests"):
        if hasattr(usage, key):
            data[key] = getattr(usage, key)
    return data
