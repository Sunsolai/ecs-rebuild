"""Embedding client — OpenAI-compatible HTTP (local BGE service or DashScope)."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from packages.shared.config import get_settings


def build_embeddings() -> OpenAIEmbeddings:
    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.embed_model,
        openai_api_base=settings.embed_base_url,
        openai_api_key=settings.embed_api_key or settings.api_key or "EMPTY",
        check_embedding_ctx_length=False,
    )
