"""对账钉批双写两轨：本台只允许单读轨（切流账册），双写一律拒绝。"""
from __future__ import annotations

from app.services import pin_batch as pin_svc
from app.services.errors import ServiceError


def apply_dualwrite(note: str = "", db_path: str | None = None) -> dict:
    raise ServiceError(
        "双写两轨未启用：本台只走切流账册单读轨，禁止双开",
        409,
    )


def dual_board(db_path: str | None = None) -> dict:
    snap = pin_svc.snapshot(db_path)
    return {
        "title": "对账钉批双写面",
        "dual_chip": "未启用",
        "enabled": False,
        "reason": "单读轨（切流账册）已收口，双写禁止双开",
        "active_read": snap["active_read"],
        "batch_code": snap["batch_code"],
        "gate_allows": snap["gate_allows"],
    }


def half_dual(db_path: str | None = None) -> dict:
    return dual_board(db_path)
