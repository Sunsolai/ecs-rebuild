"""Postsale domain tools."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from uuid import uuid4

from langchain_core.tools import tool
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from packages.shared.db.models import OrderDetail, Postsale, PostsaleReason
from packages.shared.db.session import SessionLocal

PostsaleType = Literal["退款", "退货", "换货"]


@tool
def list_postsale_eligible_items(order_id: str) -> dict[str, Any]:
    """列出订单中可申请售后的明细行。"""
    with SessionLocal() as session:
        details = (
            session.query(OrderDetail)
            .filter(
                OrderDetail.order_id == order_id,
                or_(
                    ~OrderDetail.postsale.any(),
                    and_(
                        OrderDetail.postsale.any(),
                        OrderDetail.postsale.any(Postsale.complete_time != None),  # noqa: E711
                    ),
                ),
            )
            .all()
        )
        items = [
            {
                "order_detail_id": d.order_detail_id,
                "sku_name": d.sku_name,
                "sku_count": d.sku_count,
                "total_amount": float(d.total_amount),
                "discount_amount": float(d.discount_amount or 0),
                "final_amount": float(d.final_amount),
            }
            for d in details
        ]
    if not items:
        return {"ok": False, "message": "没有可申请售后的订单明细", "items": []}
    return {"ok": True, "items": items}


@tool
def list_postsale_reasons(order_detail_id: str) -> dict[str, Any]:
    """按商品类别返回可选售后原因。"""
    with SessionLocal() as session:
        detail = (
            session.query(OrderDetail)
            .options(joinedload(OrderDetail.sku))
            .filter_by(order_detail_id=order_detail_id)
            .first()
        )
        if not detail:
            return {"ok": False, "message": "订单明细不存在"}
        category = detail.sku.sku_category
        reasons = (
            session.query(PostsaleReason)
            .filter(
                or_(
                    PostsaleReason.product_category.is_(None),
                    PostsaleReason.product_category == category,
                )
            )
            .all()
        )
        return {
            "ok": True,
            "order_detail_id": order_detail_id,
            "reasons": [r.postsale_reason for r in reasons] + ["其他"],
            "types": ["退款", "退货", "换货"],
        }


@tool
def commit_postsale(
    order_detail_id: str,
    postsale_type: PostsaleType,
    postsale_reason: str,
) -> dict[str, Any]:
    """提交售后申请（退款/退货/换货）。"""
    with SessionLocal() as session:
        detail = (
            session.query(OrderDetail)
            .options(joinedload(OrderDetail.order))
            .filter_by(order_detail_id=order_detail_id)
            .first()
        )
        if not detail:
            return {"ok": False, "message": "订单明细不存在"}

        postsale = Postsale(
            postsale_id="pts" + uuid4().hex[:16],
            create_time=datetime.now(),
            order_detail_id=order_detail_id,
            postsale_reason=postsale_reason,
            postsale_status="审核中",
            receive_id=detail.order.receive_id,
            complete_time=None,
            refund_amount=None if postsale_type == "换货" else detail.final_amount,
            postsale_type=postsale_type,
        )

        auto_msg: Optional[str] = None
        delivered = detail.order.delivered_time
        if (
            postsale_reason == "不喜欢/不想要了"
            and delivered
            and datetime.now() - delivered < timedelta(days=7)
            and float(detail.total_amount) < 100
            and postsale_type in ("退货", "换货")
        ):
            postsale.postsale_status = "退货中" if postsale_type == "退货" else "换退货"
            auto_msg = f"满足7天退换货条件，系统将自动为您安排{postsale_type}"

        session.add(postsale)
        session.commit()
        postsale_id = postsale.postsale_id
        status = postsale.postsale_status

    if auto_msg:
        return {
            "ok": True,
            "postsale_id": postsale_id,
            "status": status,
            "message": auto_msg,
        }
    return {
        "ok": True,
        "postsale_id": postsale_id,
        "status": status,
        "message": f"您的{postsale_type}申请已提交，审核结果将在48小时内通知您",
    }


POSTSALE_TOOLS = [
    list_postsale_eligible_items,
    list_postsale_reasons,
    commit_postsale,
]
