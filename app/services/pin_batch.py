"""对账钉批落点：切流账册钉住当刻批次号与坏件指纹，供对账只读引用。

单一读轨（切流账册）是唯一允许的落点；双写两轨一律拒绝，避免双开。
所有写入走整笔事务；失败抛白话。
"""
from __future__ import annotations

import hashlib
import sqlite3

from app.db import get_db
from app.services.errors import ServiceError

SLUG = "pin_batch"
CHIP_OK = "钉批已亮"
CHIP_BAD = "库无钉批"
TITLE = "对账钉批"
READ_CUTOVER = "cutover_book"
READ_OLD = "old_track"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ------------------------------------------------------------------ 指纹
def bad_fingerprint(batch_id: int, db_path: str | None = None) -> str:
    """按条目键排序，对坏件的键/质量/载荷取指纹；空集合也有稳定指纹。"""
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT item_key, quality, payload FROM capture_items
            WHERE batch_id=? AND quality!='合格'
            ORDER BY item_key
            """,
            (batch_id,),
        ).fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['item_key']}\x1f{r['quality']}\x1f{r['payload']}\x1e".encode("utf-8"))
    return h.hexdigest()[:16]


def _item_fingerprint(item_key: str, quality: str, payload: str) -> str:
    h = hashlib.sha256()
    h.update(f"{item_key}\x1f{quality}\x1f{payload}".encode("utf-8"))
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ 读端
def panel_chip(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{SLUG}_panel_chip", CHIP_BAD)


def active_read_ref(db_path: str | None = None) -> str:
    return READ_CUTOVER if active_pin(db_path) else READ_OLD


def cutover_fp(db_path: str | None = None) -> str:
    pin = active_pin(db_path)
    return pin["bad_fingerprint"] if pin else ""


def reject_refresh(db_path: str | None = None) -> bool:
    if not active_pin(db_path):
        return False
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{SLUG}_reject_refresh", "0") == "1"


def pinned_batch_code(db_path: str | None = None) -> str:
    return (active_pin(db_path) or {}).get("batch_code", "")


def active_pin(db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM pin_batch_ledger ORDER BY id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def ledger_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pin_batch_ledger ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def snapshot_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pin_batch_snapshot ORDER BY item_key"
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------ 落点
def commit_batch(batch_id: int, note: str = "", db_path: str | None = None) -> dict:
    """整笔提交钉批落点：批次号 + 坏件指纹 + 快照行，一并成功或一并失败。"""
    try:
        with get_db(db_path) as conn:
            # 串行化：抢到写锁后再判重，后到者必见先到者的落点。
            conn.execute("BEGIN IMMEDIATE")
            batch = conn.execute(
                "SELECT * FROM capture_batches WHERE id=?", (int(batch_id),)
            ).fetchone()
            if not batch:
                raise ServiceError("批次不存在，钉批未落台")

            existing = conn.execute(
                "SELECT * FROM pin_batch_ledger ORDER BY id LIMIT 1"
            ).fetchone()
            if existing:
                raise ServiceError(
                    f"已钉批 {existing['batch_code']}，同一读轨禁止再次钉批或双开",
                    409,
                )

            items = conn.execute(
                """
                SELECT id, item_key, quality, payload FROM capture_items
                WHERE batch_id=? AND quality!='合格'
                ORDER BY item_key
                """,
                (batch["id"],),
            ).fetchall()

            h = hashlib.sha256()
            for it in items:
                h.update(
                    f"{it['item_key']}\x1f{it['quality']}\x1f{it['payload']}\x1e".encode(
                        "utf-8"
                    )
                )
            fingerprint = h.hexdigest()[:16]

            cur = conn.execute(
                """
                INSERT INTO pin_batch_ledger(
                  batch_id, batch_code, bad_fingerprint, bad_count, note
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (batch["id"], batch["batch_code"], fingerprint, len(items), note or ""),
            )
            ledger_id = cur.lastrowid
            conn.executemany(
                """
                INSERT INTO pin_batch_snapshot(
                  ledger_id, item_id, item_key, quality, item_fingerprint
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        ledger_id,
                        it["id"],
                        it["item_key"],
                        it["quality"],
                        _item_fingerprint(it["item_key"], it["quality"], it["payload"]),
                    )
                    for it in items
                ],
            )

            _meta_set(conn, f"{SLUG}_panel_chip", CHIP_OK)
            _meta_set(conn, f"{SLUG}_pinned_batch_code", batch["batch_code"])
            _meta_set(conn, f"{SLUG}_reject_refresh", "1")
            _meta_set(conn, f"{SLUG}_active_read", READ_CUTOVER)
            _meta_set(conn, f"{SLUG}_fingerprint", fingerprint)
            conn.execute(
                """
                INSERT INTO audit_events(actor, action, entity_type, entity_id, detail)
                VALUES ('admin', '钉批落台', 'pin_batch', ?, ?)
                """,
                (
                    ledger_id,
                    f"{batch['batch_code']} fp={fingerprint} bad={len(items)}",
                ),
            )
    except ServiceError:
        raise
    except sqlite3.IntegrityError:
        # 另一写入者已抢先落点，本笔整笔回滚。
        raise ServiceError("已钉批，同一读轨禁止再次钉批或双开", 409) from None
    except sqlite3.OperationalError as exc:
        raise ServiceError(f"钉批写入失败，请稍后重试：{exc}", 409) from exc

    return {
        "ok": True,
        "chip": CHIP_OK,
        "title": TITLE,
        "batch_id": batch["id"],
        "batch_code": batch["batch_code"],
        "fingerprint": fingerprint,
        "bad_count": len(items),
        "active_read": READ_CUTOVER,
        "reject_refresh": True,
        "message": f"{TITLE}已落台：{batch['batch_code']}",
    }


def commit_action(payload: dict | None = None, db_path: str | None = None) -> dict:
    """后台落台入口：必须点名批次，整笔提交。"""
    payload = payload or {}
    raw = payload.get("batch_id")
    try:
        batch_id = int(raw)
    except (TypeError, ValueError):
        raise ServiceError("钉批必须点名批次，未落台") from None
    if batch_id <= 0:
        raise ServiceError("钉批必须点名批次，未落台")
    return commit_batch(batch_id, str(payload.get("note") or ""), db_path)


# ------------------------------------------------------------------ 闸
def _misalign_reasons(conn, ledger: dict | None, chip: str) -> list[str]:
    reasons: list[str] = []
    if not ledger:
        reasons.append("库无钉批落点")
        if chip == CHIP_OK:
            reasons.append("只有钉批芯片、无落点行")
        return reasons

    if chip != CHIP_OK:
        reasons.append("钉批芯片未亮")
    shown_code = _meta_get(conn, f"{SLUG}_pinned_batch_code", ledger["batch_code"])
    if shown_code != ledger["batch_code"]:
        reasons.append(
            f"钉批芯片批次号与落点对不齐（芯片{shown_code} / 落点{ledger['batch_code']}）"
        )
    if _meta_get(conn, f"{SLUG}_reject_refresh", "0") != "1":
        reasons.append("钉批未拒回刷")

    items = conn.execute(
        """
        SELECT item_key, quality, payload FROM capture_items
        WHERE batch_id=? AND quality!='合格'
        ORDER BY item_key
        """,
        (ledger["batch_id"],),
    ).fetchall()
    h = hashlib.sha256()
    for it in items:
        h.update(
            f"{it['item_key']}\x1f{it['quality']}\x1f{it['payload']}\x1e".encode("utf-8")
        )
    if h.hexdigest()[:16] != ledger["bad_fingerprint"]:
        reasons.append(
            f"坏件指纹拧花：落点{ledger['bad_fingerprint']} / 现行{h.hexdigest()[:16]}"
        )
    return reasons


def snapshot(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        ledger = conn.execute(
            "SELECT * FROM pin_batch_ledger ORDER BY id LIMIT 1"
        ).fetchone()
        ledger = dict(ledger) if ledger else None
        chip = _meta_get(conn, f"{SLUG}_panel_chip", CHIP_BAD)
        reasons = _misalign_reasons(conn, ledger, chip)
        reject_ok = bool(ledger) and (
            _meta_get(conn, f"{SLUG}_reject_refresh", "0") == "1"
        )
    return {
        "title": TITLE,
        "chip": chip,
        "panel_chip": chip,
        "ledger_present": ledger is not None,
        "batch_id": ledger["batch_id"] if ledger else 0,
        "batch_code": ledger["batch_code"] if ledger else "",
        "pinned_fingerprint": ledger["bad_fingerprint"] if ledger else "",
        "bad_count": ledger["bad_count"] if ledger else 0,
        "active_read": READ_CUTOVER if ledger else READ_OLD,
        "reject_refresh": reject_ok,
        "fingerprint_match": ledger is not None
        and not any("指纹" in r for r in reasons),
        "aligned": ledger is not None and not reasons,
        "gate_allows": ledger is not None and not reasons,
        "misalign_reasons": reasons,
    }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    return snapshot(db_path)["gate_allows"]


def require_pack_or_raise(db_path: str | None = None) -> None:
    snap = snapshot(db_path)
    if not snap["gate_allows"]:
        detail = "；".join(snap["misalign_reasons"]) or "读轨未对齐"
        raise ServiceError(f"{TITLE}已挡住：{detail}", 409)
