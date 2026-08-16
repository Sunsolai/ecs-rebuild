"""Logistics domain tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from langchain_core.tools import tool
from sqlalchemy.orm import joinedload

from packages.shared.db.models import (
    Logistics,
    LogisticsCompany,
    LogisticsComplaint,
    LogisticsComplaintsRecord,
    OrderInfo,
)
from packages.shared.db.session import SessionLocal


@tool
def list_logistics_companies() -> dict[str, Any]:
    """列出平台支持的快递公司。"""
    with SessionLocal() as session:
        companies = [c.company_name for c in session.query(LogisticsCompany).all()]
    return {"ok": True, "companies": companies}


@tool
def get_logistics_info(order_id: str) -> dict[str, Any]:
    """根据订单 ID 查询物流轨迹。"""
    with SessionLocal() as session:
        order = (
            session.query(OrderInfo)
            .options(joinedload(OrderInfo.logistics))
            .options(joinedload(OrderInfo.order_detail))
            .filter_by(order_id=order_id)
            .first()
        )
        if not order:
            return {"ok": False, "message": "订单不存在"}
        if not order.logistics:
            return {"ok": False, "message": "该订单暂无物流信息"}
        logistics = order.logistics[0]
        tracking = (logistics.logistics_tracking or "").split("\n")
        return {
            "ok": True,
            "order_id": order_id,
            "items": [f"{d.sku_name} × {d.sku_count}" for d in order.order_detail],
            "logistics_id": logistics.logistics_id,
            "tracking": tracking,
        }


@tool
def list_logistics_complaint_reasons(logistics_id: str) -> dict[str, Any]:
    """按物流状态返回常见投诉原因选项。"""
    with SessionLocal() as session:
        logistics = (
            session.query(Logistics).filter_by(logistics_id=logistics_id).first()
        )
        if not logistics:
            return {"ok": False, "message": "物流单不存在"}
        status = "已发货" if logistics.delivered_time is None else "已签收"
        reasons = (
            session.query(LogisticsComplaint)
            .filter_by(logistics_status=status)
            .all()
        )
        return {
            "ok": True,
            "logistics_id": logistics_id,
            "status": status,
            "reasons": [r.logistics_complaint for r in reasons] + ["其他"],
        }


@tool
def record_logistics_complaint(
    user_id: str,
    logistics_id: str,
    complaint: str,
) -> dict[str, Any]:
    """提交物流投诉记录。"""
    if not complaint or not complaint.strip():
        return {"ok": False, "message": "投诉内容不能为空"}
    with SessionLocal() as session:
        logistics = (
            session.query(Logistics).filter_by(logistics_id=logistics_id).first()
        )
        if not logistics:
            return {"ok": False, "message": "物流单不存在"}
        session.add(
            LogisticsComplaintsRecord(
                logistics_id=logistics_id,
                logistics_complaint=complaint.strip(),
                complaint_time=datetime.now(),
                user_id=user_id,
            )
        )
        session.commit()
    return {"ok": True, "message": "您的投诉已经收到，我们会尽快处理。"}


LOGISTICS_TOOLS = [
    list_logistics_companies,
    get_logistics_info,
    list_logistics_complaint_reasons,
    record_logistics_complaint,
]
