"""Specialist agents built with LangGraph create_react_agent."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from apps.orchestrator.llm import build_chat_model
from apps.orchestrator.state import AgentState
from apps.tools import LOGISTICS_TOOLS, ORDER_TOOLS, POSTSALE_TOOLS
from packages.shared.config import get_settings


def _user_context(state: AgentState) -> str:
    return (
        f"当前会话 user_id={state.get('user_id')}。"
        "调用业务工具时必须传入该 user_id。"
        "对取消订单、改址、提交售后等写操作，先向用户确认再执行。"
        "用简洁中文回复，必要时用列表展示选项。"
    )


def _run_react(agent, state: AgentState, system: str) -> dict:
    messages = [
        SystemMessage(content=system + "\n" + _user_context(state)),
        *list(state["messages"]),
    ]
    result = agent.invoke({"messages": messages})
    # Only append new AI/tool messages beyond the input history length
    new_messages = result["messages"][len(messages) :]
    if not new_messages:
        # Fallback: take last AI message
        new_messages = result["messages"][-1:]
    return {"messages": new_messages, "next_agent": "FINISH"}


ORDER_SYSTEM = (
    "你是订单专家 Agent。可查询订单、修改收货信息、取消未发货订单。"
    "改址前先列出可选地址或引导用户提供省市区；取消前必须 confirm=True 二次确认。"
)

LOGISTICS_SYSTEM = (
    "你是物流专家 Agent。可查快递公司、订单物流轨迹、提交物流投诉。"
    "投诉前先列出常见原因供用户选择。"
)

POSTSALE_SYSTEM = (
    "你是售后专家 Agent。协助退款/退货/换货。"
    "流程：选可售后明细 → 选类型与原因 → 提交。写操作前先确认。"
)

KNOWLEDGE_SYSTEM = (
    "你是商品知识专家。根据检索工具返回的图谱结果，用清晰中文回答商品相关问题。"
    "不要编造库存外的信息；检索为空时如实说明。"
)

CHITCHAT_SYSTEM = (
    "你是电商客服闲聊助手。礼貌、简短地回应问候与闲聊，"
    "并引导用户提出订单、物流、售后或商品问题。"
)


@tool
def search_product_knowledge(query: str, user_id: str = "") -> dict:
    """检索商品知识图谱（GraphRAG），回答规格、品牌、推荐等问题。"""
    settings = get_settings()
    if not settings.knowledge_enabled:
        return {"ok": False, "message": "知识检索未启用", "documents": []}
    import asyncio

    from apps.knowledge.graphrag import get_graphrag_service

    service = get_graphrag_service()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    lambda: asyncio.run(service.search(query, user_id=user_id or None))
                ).result()
        return loop.run_until_complete(service.search(query, user_id=user_id or None))
    except RuntimeError:
        return asyncio.run(service.search(query, user_id=user_id or None))


def build_order_agent():
    return create_react_agent(build_chat_model(), ORDER_TOOLS)


def build_logistics_agent():
    return create_react_agent(build_chat_model(), LOGISTICS_TOOLS)


def build_postsale_agent():
    return create_react_agent(build_chat_model(), POSTSALE_TOOLS)


def build_knowledge_agent():
    return create_react_agent(build_chat_model(), [search_product_knowledge])


_order_agent = None
_logistics_agent = None
_postsale_agent = None
_knowledge_agent = None


def order_node(state: AgentState) -> dict:
    global _order_agent
    if _order_agent is None:
        _order_agent = build_order_agent()
    return _run_react(_order_agent, state, ORDER_SYSTEM)


def logistics_node(state: AgentState) -> dict:
    global _logistics_agent
    if _logistics_agent is None:
        _logistics_agent = build_logistics_agent()
    return _run_react(_logistics_agent, state, LOGISTICS_SYSTEM)


def postsale_node(state: AgentState) -> dict:
    global _postsale_agent
    if _postsale_agent is None:
        _postsale_agent = build_postsale_agent()
    return _run_react(_postsale_agent, state, POSTSALE_SYSTEM)


def knowledge_node(state: AgentState) -> dict:
    global _knowledge_agent
    if _knowledge_agent is None:
        _knowledge_agent = build_knowledge_agent()
    return _run_react(_knowledge_agent, state, KNOWLEDGE_SYSTEM)


def chitchat_node(state: AgentState) -> dict:
    llm = build_chat_model(temperature=0.7)
    reply = llm.invoke(
        [
            SystemMessage(content=CHITCHAT_SYSTEM),
            *list(state["messages"])[-6:],
        ]
    )
    return {"messages": [reply], "next_agent": "FINISH"}
