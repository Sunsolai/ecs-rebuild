"""LLM factory for DashScope OpenAI-compatible API."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from packages.shared.config import get_settings


def build_chat_model(temperature: float = 0.2, model: str | None = None) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=model or settings.llm_model,
        api_key=settings.api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
    )
