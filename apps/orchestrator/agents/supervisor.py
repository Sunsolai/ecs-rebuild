"""Supervisor router — picks the specialist agent for the current turn."""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from apps.orchestrator.llm import build_chat_model
from apps.orchestrator.state import AgentState

RouteTarget = Literal[
    "order", "logistics", "postsale", "knowledge", "chitchat", "FINISH"
]


class RouteDecision(BaseModel):
    next_agent: RouteTarget = Field(
        description=(
            "order=订单查询/改址/取消; "
            "logistics=物流查询/快递公司/物流投诉; "
            "postsale=退款退货换货; "
            "knowledge=商品知识/推荐/属性问答; "
            "chitchat=闲聊或无法归类; "
            "FINISH=本轮已完整回答无需继续"
        )
    )
    rationale: str = Field(description="简短路由理由")


SUPERVISOR_SYSTEM = """你是电商客服系统的 Supervisor，负责把用户请求路由到正确的专家 Agent。
当前会话 user_id 会在上下文中给出，业务工具需要该 ID。

路由规则：
- 查订单、改收货地址、取消订单 → order
- 查物流、快递公司、物流投诉 → logistics
- 退款/退货/换货售后 → postsale
- 商品规格、品牌、推荐、目录知识 → knowledge
- 打招呼、闲聊、感谢、无法归类 → chitchat
- 若上一轮专家已给出完整答复且用户未提新需求 → FINISH

只输出结构化路由结果。"""


def supervisor_node(state: AgentState) -> dict:
    llm = build_chat_model(temperature=0).with_structured_output(RouteDecision)
    recent = list(state["messages"])[-8:]
    user_hint = HumanMessage(
        content=f"当前 user_id={state.get('user_id', '')}。请根据对话选择 next_agent。"
    )
    decision: RouteDecision = llm.invoke(
        [SystemMessage(content=SUPERVISOR_SYSTEM), user_hint, *recent]
    )
    return {"next_agent": decision.next_agent}
