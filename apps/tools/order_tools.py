"""Order domain tools — ported from Rasa custom actions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from uuid import uuid4

from langchain_core.tools import tool
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from packages.shared.db.models import OrderInfo, OrderStatus, Postsale, ReceiveInfo, Region
from packages.shared.db.session import SessionLocal

FilterKind = Literal[
    "in_progress_or_completed_3d",
    "before_shipped",
    "before_delivered",
    "shipped",
    "shipped_or_delivered",
    "after_delivered",
]


def _order_filter(user_id: str, kind: FilterKind):
    base = OrderInfo.user_id == user_id
    match kind:
        case "shipped":
            return and_(base, OrderInfo.order_status == "已发货")
        case "shipped_or_delivered":
            return and_(base, OrderInfo.order_status.in_(["已发货", "已签收"]))
        case "in_progress_or_completed_3d":
            return and_(
                base,
                OrderInfo.order_status != "已取消",
                or_(
                    OrderInfo.order_status != "已完成",
                    OrderInfo.complete_time > datetime.now() - timedelta(days=3),
                ),
            )
        case "before_delivered":
            return and_(
                base,
                OrderInfo.order_status != "已取消",
                OrderStatus.status_code <= 320,
            )
        case "before_shipped":
            return and_(
                base,
                OrderInfo.order_status != "已取消",
                OrderStatus.status_code <= 310,
            )
        case "after_delivered":
            return and_(
                base,
                OrderInfo.order_status != "已取消",
                OrderStatus.status_code >= 330,
            )
        case _:
            return and_(base, OrderInfo.order_status != "已取消")


@tool
def list_orders(
    user_id: str,
    filter_kind: FilterKind = "in_progress_or_completed_3d",
) -> dict[str, Any]:
    """按业务场景列出用户订单，供用户选择。

    filter_kind:
    - in_progress_or_completed_3d: 进行中或近3日已完成（查详情）
    - before_shipped: 未发货（可取消）
    - before_delivered: 未签收（可改址）
    - shipped: 已发货
    - shipped_or_delivered: 已发货或已签收（物流投诉）
    - after_delivered: 已签收及之后（售后）
    """
    with SessionLocal() as session:
        orders = (
            session.query(OrderInfo)
            .join(OrderInfo.order_status_)
            .options(joinedload(OrderInfo.order_detail))
            .filter(_order_filter(user_id, filter_kind))
            .all()
        )
        items = []
        for o in orders:
            items.append(
                {
                    "order_id": o.order_id,
                    "order_status": o.order_status,
                    "items": [
                        f"{d.sku_name} × {d.sku_count}" for d in o.order_detail
                    ],
                }
            )
    if not items:
        return {"ok": False, "message": "未查询到符合条件的订单", "orders": []}
    return {"ok": True, "count": len(items), "orders": items}


@tool
def get_order_detail(order_id: str) -> dict[str, Any]:
    """查询订单详情，含明细、收货信息、最近物流与售后摘要。"""
    with SessionLocal() as session:
        order = (
            session.query(OrderInfo)
            .options(joinedload(OrderInfo.order_detail))
            .options(joinedload(OrderInfo.logistics))
            .options(joinedload(OrderInfo.receive))
            .options(joinedload(OrderInfo.order_status_))
            .filter_by(order_id=order_id)
            .first()
        )
        if not order:
            return {"ok": False, "message": f"订单不存在: {order_id}"}

        lines = []
        total_amount = discount = final = 0.0
        for d in order.order_detail:
            lines.append(
                {
                    "sku_name": d.sku_name,
                    "sku_count": d.sku_count,
                    "total_amount": float(d.total_amount),
                    "discount_amount": float(d.discount_amount or 0),
                    "final_amount": float(d.final_amount),
                }
            )
            total_amount += float(d.total_amount)
            discount += float(d.discount_amount or 0)
            final += float(d.final_amount)

        receive = {
            "name": order.receive.receiver_name,
            "phone": order.receive.receiver_phone,
            "address": (
                f"{order.receive.receive_province}"
                f"{order.receive.receive_city}"
                f"{order.receive.receive_district}"
                f"{order.receive.receive_street_address}"
            ),
        }
        logistics_tip = None
        if order.logistics:
            tracking = order.logistics[0].logistics_tracking or ""
            logistics_tip = tracking.splitlines()[-1] if tracking else None

        postsale_summary = []
        if order.order_status_.status_code >= 400:
            detail_ids = [d.order_detail_id for d in order.order_detail]
            subquery = (
                session.query(
                    Postsale.order_detail_id,
                    func.max(Postsale.create_time).label("max_time"),
                )
                .filter(Postsale.order_detail_id.in_(detail_ids))
                .group_by(Postsale.order_detail_id)
                .subquery()
            )
            latest = (
                session.query(Postsale)
                .join(
                    subquery,
                    and_(
                        Postsale.order_detail_id == subquery.c.order_detail_id,
                        Postsale.create_time == subquery.c.max_time,
                    ),
                )
                .all()
            )
            for p in latest:
                postsale_summary.append(
                    {
                        "postsale_id": p.postsale_id,
                        "type": p.postsale_type.value if p.postsale_type else None,
                        "status": p.postsale_status,
                        "reason": p.postsale_reason,
                    }
                )

    return {
        "ok": True,
        "order_id": order.order_id,
        "order_status": order.order_status,
        "times": {
            "create": str(order.create_time) if order.create_time else None,
            "payment": str(order.payment_time) if order.payment_time else None,
            "delivered": str(order.delivered_time) if order.delivered_time else None,
            "complete": str(order.complete_time) if order.complete_time else None,
        },
        "line_items": lines,
        "amounts": {
            "total": total_amount,
            "discount": discount,
            "final": final,
        },
        "receive": receive,
        "latest_logistics": logistics_tip,
        "postsale": postsale_summary,
    }


@tool
def list_receive_addresses(user_id: str) -> dict[str, Any]:
    """列出用户已有收货地址。"""
    with SessionLocal() as session:
        rows = session.query(ReceiveInfo).filter_by(user_id=user_id).all()
        addresses = [
            {
                "receive_id": r.receive_id,
                "name": r.receiver_name,
                "phone": r.receiver_phone,
                "province": r.receive_province,
                "city": r.receive_city,
                "district": r.receive_district,
                "street": r.receive_street_address,
            }
            for r in rows
        ]
    return {"ok": True, "addresses": addresses}


@tool
def list_provinces() -> dict[str, Any]:
    """列出可选省份。"""
    with SessionLocal() as session:
        provinces = sorted({r.province for r in session.query(Region).all()})
    return {"ok": True, "provinces": provinces}


@tool
def list_cities(province: str) -> dict[str, Any]:
    """按省列出城市。"""
    with SessionLocal() as session:
        cities = sorted(
            {
                r.city
                for r in session.query(Region).filter_by(province=province).all()
            }
        )
    return {"ok": True, "province": province, "cities": cities}


@tool
def list_districts(province: str, city: str) -> dict[str, Any]:
    """按省市列出区县。"""
    with SessionLocal() as session:
        districts = sorted(
            {
                r.district
                for r in session.query(Region)
                .filter_by(province=province, city=city)
                .all()
            }
        )
    return {"ok": True, "province": province, "city": city, "districts": districts}


@tool
def update_order_receive_info(
    user_id: str,
    order_id: str,
    receive_id: Optional[str] = None,
    receiver_name: Optional[str] = None,
    receiver_phone: Optional[str] = None,
    receive_province: Optional[str] = None,
    receive_city: Optional[str] = None,
    receive_district: Optional[str] = None,
    receive_street_address: Optional[str] = None,
) -> dict[str, Any]:
    """修改订单收货信息。可传已有 receive_id，或传完整新地址字段创建后绑定。"""
    with SessionLocal() as session:
        order = session.query(OrderInfo).filter_by(order_id=order_id).first()
        if not order:
            return {"ok": False, "message": "未找到订单"}
        if order.user_id != user_id:
            return {"ok": False, "message": "无权操作该订单"}

        if receive_id:
            recv = session.query(ReceiveInfo).filter_by(receive_id=receive_id).first()
            if not recv:
                return {"ok": False, "message": "收货信息不存在"}
        else:
            required = [
                receiver_name,
                receiver_phone,
                receive_province,
                receive_city,
                receive_district,
                receive_street_address,
            ]
            if not all(required):
                return {
                    "ok": False,
                    "message": "新建地址需提供姓名、电话、省市区与详细地址",
                }
            existing = (
                session.query(ReceiveInfo)
                .filter_by(
                    user_id=user_id,
                    receiver_name=receiver_name,
                    receiver_phone=receiver_phone,
                    receive_province=receive_province,
                    receive_city=receive_city,
                    receive_district=receive_district,
                    receive_street_address=receive_street_address,
                )
                .first()
            )
            if existing:
                recv = existing
            else:
                recv = ReceiveInfo(
                    receive_id="rec" + uuid4().hex[:16],
                    user_id=user_id,
                    receiver_name=receiver_name,
                    receiver_phone=receiver_phone,
                    receive_province=receive_province,
                    receive_city=receive_city,
                    receive_district=receive_district,
                    receive_street_address=receive_street_address,
                )
                session.add(recv)
                session.flush()

        order.receive_id = recv.receive_id
        session.commit()
        return {
            "ok": True,
            "message": "订单收货信息已修改",
            "receive_id": recv.receive_id,
        }


@tool
def cancel_order(user_id: str, order_id: str, confirm: bool = False) -> dict[str, Any]:
    """取消订单。confirm=False 时仅返回预览；confirm=True 时真正取消。仅允许未发货订单。"""
    with SessionLocal() as session:
        order = (
            session.query(OrderInfo)
            .join(OrderInfo.order_status_)
            .filter_by(order_id=order_id)
            .first()
        )
        if not order:
            return {"ok": False, "message": "未找到该订单"}
        if order.user_id != user_id:
            return {"ok": False, "message": "无权操作该订单"}
        if order.order_status_ and order.order_status_.status_code > 310:
            return {"ok": False, "message": "订单已发货，无法取消"}
        if order.order_status == "已取消":
            return {"ok": False, "message": "订单已是取消状态"}

        if not confirm:
            return {
                "ok": True,
                "need_confirm": True,
                "order_id": order_id,
                "order_status": order.order_status,
                "message": "请确认是否取消该订单",
            }

        old_status = order.order_status
        order.order_status = "已取消"
        order.complete_time = datetime.now()
        session.commit()

        msg = "订单已取消"
        if old_status == "待发货":
            msg += "，退款金额将在24小时内返还您的账户"
        return {"ok": True, "message": msg, "order_id": order_id}


ORDER_TOOLS = [
    list_orders,
    get_order_detail,
    list_receive_addresses,
    list_provinces,
    list_cities,
    list_districts,
    update_order_receive_info,
    cancel_order,
]
