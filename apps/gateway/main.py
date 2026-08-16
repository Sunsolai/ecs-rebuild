"""FastAPI conversation gateway — Scheme A entrypoint."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.gateway.schemas import ChatRequest, ChatResponse, HealthResponse
from apps.orchestrator.graph import chat
from packages.shared.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm settings on startup
    get_settings()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ECS Rebuild Gateway",
        description="LangGraph multi-agent e-commerce CS (Scheme A)",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", app=settings.app_name, env=settings.app_env
        )

    @app.post("/v1/chat", response_model=ChatResponse)
    def chat_endpoint(body: ChatRequest) -> ChatResponse:
        user_id = body.user_id or settings.default_user_id
        thread_id = body.thread_id or str(uuid.uuid4())
        try:
            result = chat(
                body.message,
                user_id=user_id,
                thread_id=thread_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ChatResponse(**result)

    return app


app = create_app()
