"""LangGraph conversation state."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    thread_id: str
    next_agent: Optional[
        Literal[
            "order",
            "logistics",
            "postsale",
            "knowledge",
            "chitchat",
            "FINISH",
        ]
    ]
