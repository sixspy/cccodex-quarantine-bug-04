"""对账钉批切流账册：钉批唯一读轨。双写两轨禁止双开。"""
from __future__ import annotations

from app.services import pin_batch as pin_svc
from app.services.errors import ServiceError

SLUG = "pin_batch"


def append_cutover(ref_id: int, note: str, db_path: str | None = None) -> dict:
    """点名批次落台；ref_id 即批次 id。旧的软笔记路径不再写读轨。"""
    if not ref_id:
        raise ServiceError("切流账册必须点名批次，未落台")
    out = pin_svc.commit_action({"batch_id": ref_id, "note": note}, db_path)
    out["ref_id"] = ref_id
    return out


def cutover_rows(db_path: str | None = None) -> list[dict]:
    snap = pin_svc.snapshot(db_path)
    return [
        {
            "batch_id": row["batch_id"],
            "batch_code": row["batch_code"],
            "fingerprint": row["bad_fingerprint"],
            "bad_count": row["bad_count"],
            "chip": snap["chip"],
            "active_read": snap["active_read"],
        }
        for row in pin_svc.ledger_rows(db_path)
    ]


def board(db_path: str | None = None) -> dict:
    snap = pin_svc.snapshot(db_path)
    return {
        "title": pin_svc.TITLE,
        "chip": snap["chip"],
        "panel_chip": snap["chip"],
        "batch_code": snap["batch_code"],
        "pinned_fingerprint": snap["pinned_fingerprint"],
        "bad_count": snap["bad_count"],
        "active_read": snap["active_read"],
        "reject_refresh": snap["reject_refresh"],
        "fingerprint_match": snap["fingerprint_match"],
        "gate_allows": snap["gate_allows"],
        "aligned": snap["aligned"],
        "misalign_reasons": snap["misalign_reasons"],
        "cutover": cutover_rows(db_path),
        "fate": "cutover_book",
    }


def require_ready(db_path: str | None = None) -> None:
    if pin_svc.snapshot(db_path)["active_read"] != pin_svc.READ_CUTOVER:
        raise ServiceError("切流账册未落台，禁止继续", 409)
