"""LangGraph multi-agent orchestrator (Scheme A)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from apps.orchestrator.agents.specialists import (
    chitchat_node,
    knowledge_node,
    logistics_node,
    order_node,
    postsale_node,
)
from apps.orchestrator.agents.supervisor import supervisor_node
from apps.orchestrator.state import AgentState
from packages.shared.config import get_settings


def _route_after_supervisor(state: AgentState) -> str:
    nxt = state.get("next_agent") or "chitchat"
    if nxt == "FINISH":
        return END
    return nxt


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("order", order_node)
    graph.add_node("logistics", logistics_node)
    graph.add_node("postsale", postsale_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("chitchat", chitchat_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "order": "order",
            "logistics": "logistics",
            "postsale": "postsale",
            "knowledge": "knowledge",
            "chitchat": "chitchat",
            END: END,
        },
    )
    for name in ("order", "logistics", "postsale", "knowledge", "chitchat"):
        graph.add_edge(name, END)

    return graph.compile(checkpointer=checkpointer)


def _build_checkpointer():
    settings = get_settings()
    backend = (settings.checkpoint_backend or "memory").lower()
    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            import sqlite3

            path = Path(settings.checkpoint_sqlite_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            return SqliteSaver(conn)
        except Exception:
            return MemorySaver()
    if backend == "postgres" and settings.checkpoint_postgres_uri:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            return PostgresSaver.from_conn_string(settings.checkpoint_postgres_uri)
        except Exception:
            return MemorySaver()
    return MemorySaver()


@lru_cache
def get_compiled_graph():
    return build_graph(_build_checkpointer())


def chat(
    message: str,
    *,
    user_id: str,
    thread_id: str,
) -> dict[str, Any]:
    """Run one conversation turn and return the assistant reply."""
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=message)],
            "user_id": user_id,
            "thread_id": thread_id,
            "next_agent": None,
        },
        config=config,
    )
    reply = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            # skip tool-call-only messages
            if isinstance(msg.content, str) and msg.content.strip():
                reply = msg.content
                break
            if isinstance(msg.content, list):
                texts = [
                    c.get("text", "")
                    for c in msg.content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                if any(texts):
                    reply = "\n".join(t for t in texts if t)
                    break
    return {
        "reply": reply or "暂时无法处理您的请求，请换一种说法试试。",
        "user_id": user_id,
        "thread_id": thread_id,
        "next_agent": result.get("next_agent"),
    }
