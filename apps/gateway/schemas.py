"""API request/response schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    user_id: Optional[str] = Field(None, description="业务用户 ID")
    thread_id: Optional[str] = Field(None, description="会话线程 ID，多轮必传同一值")


class ChatResponse(BaseModel):
    reply: str
    user_id: str
    thread_id: str
    next_agent: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str
