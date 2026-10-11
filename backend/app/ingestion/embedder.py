"""Embedding adapter.

Provider is chosen by `settings.embedding_provider`:
  - "voyage"  -> VoyageAI (`voyage-3`, 1024 dims by default)
  - "openai"  -> OpenAI (`text-embedding-3-small`, 1536 dims by default)

Both call paths batch inputs and return `list[list[float]]` in request order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("ingestion.embedder")

Mode = Literal["document", "query"]


class Embedder(ABC):
    model: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str], *, mode: Mode = "document") -> list[list[float]]: ...


class VoyageEmbedder(Embedder):
    def __init__(self, api_key: str, model: str, dim: int) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str], *, mode: Mode = "document") -> list[list[float]]:
        if not texts:
            return []
        input_type = "document" if mode == "document" else "query"
        result = self._client.embed(texts=texts, model=self.model, input_type=input_type)
        return [list(v) for v in result.embeddings]


class OpenAIEmbedder(Embedder):
    def __init__(self, api_key: str, model: str, dim: int) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str], *, mode: Mode = "document") -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [list(d.embedding) for d in resp.data]


def build_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "voyage":
        key = s.voyage_api_key.get_secret_value()
        if not key:
            raise RuntimeError("VOYAGE_API_KEY is not set (embedding_provider=voyage).")
        log.info("embedder_init", provider="voyage", model=s.embedding_model, dim=s.embedding_dim)
        return VoyageEmbedder(key, s.embedding_model, s.embedding_dim)
    if s.embedding_provider == "openai":
        key = s.openai_api_key.get_secret_value()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set (embedding_provider=openai).")
        log.info("embedder_init", provider="openai", model=s.embedding_model, dim=s.embedding_dim)
        return OpenAIEmbedder(key, s.embedding_model, s.embedding_dim)
    raise RuntimeError(f"Unknown embedding provider: {s.embedding_provider}")
