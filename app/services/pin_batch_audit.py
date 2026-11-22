"""对账钉批读轨审计：汇总单读轨落点与双写面（禁用）。"""
from __future__ import annotations

from app.db import get_db
from app.services import pin_batch as pin_svc
from app.services.pin_batch_cutover import board as cutover_board
from app.services.pin_batch_dualwrite import dual_board

_SLUG = "pin_batch"


def audit_list(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def audit_summary(db_path: str | None = None) -> dict:
    return {
        "title": "对账钉批审计",
        "events": audit_list(db_path),
        "ledger": pin_svc.ledger_rows(db_path),
        "snapshot_count": len(pin_svc.snapshot_rows(db_path)),
        "cutover": cutover_board(db_path),
        "dualwrite": dual_board(db_path),
    }
