"""Smoke tests that do not require external services."""

from apps.gateway.main import create_app
from apps.orchestrator.state import AgentState


def test_health():
    app = create_app()
    assert app.title == "ECS Rebuild Gateway"


def test_agent_state_typing():
    state: AgentState = {
        "messages": [],
        "user_id": "1",
        "thread_id": "t1",
        "next_agent": None,
    }
    assert state["user_id"] == "1"
