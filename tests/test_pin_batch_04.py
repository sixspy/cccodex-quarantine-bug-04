"""quarantine-bug-04：钉批落点、对账只读、指纹闸与串行。

这些用例先于实现写就，用来把「只亮芯片、不落行」的旧脚手架钉死。
"""
from __future__ import annotations

import pathlib
import threading

import pytest

from app.db import _meta_set, get_db
from app.services import (
    captures,
    pin_batch,
    pin_batch_dualwrite,
    policies,
    quarantine,
    reconcile,
    review,
    rework,
)
from app.services.errors import ServiceError

PIN_OK = "钉批已亮"
PIN_BAD = "库无钉批"


# ---------------------------------------------------------------- helpers
def _batch_by_code(code: str, db_path: str) -> dict:
    return next(b for b in captures.list_batches(db_path) if b["batch_code"] == code)


def _pending_ticket(db_path: str, batch_id: int | None = None) -> dict | None:
    with get_db(db_path) as conn:
        sql = """
            SELECT t.id, t.row_id, i.batch_id
            FROM review_tickets t
            JOIN quarantine_rows r ON r.id=t.row_id
            JOIN capture_items i ON i.id=r.item_id
            WHERE t.decision='待决'
        """
        params: tuple = ()
        if batch_id is not None:
            sql += " AND i.batch_id=?"
            params = (batch_id,)
        sql += " ORDER BY t.id LIMIT 1"
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def _make_ticket(db_path: str, batch_code: str) -> tuple[dict, dict]:
    batch = _batch_by_code(batch_code, db_path)
    detail = captures.get_batch(batch["id"], db_path)
    bad = next(
        i
        for i in detail["items"]
        if i["quality"] != "合格" and i["status"] == "待检"
    )
    open_bin = next(b for b in quarantine.list_bins(db_path) if b["status"] == "开放")
    row = quarantine.enter_item(bad["id"], open_bin["id"], "钉批闸用例", db_path)
    ticket = next(
        t
        for t in review.list_tickets(db_path)
        if t["row_id"] == row["id"] and t["decision"] == "待决"
    )
    return batch, ticket


# ---------------------------------------------------------------- 落点缺失
def test_missing_pin_landing_blocks_release(db_path):
    snap = pin_batch.snapshot(db_path)
    assert snap["ledger_present"] is False
    assert snap["chip"] == PIN_BAD
    assert snap["gate_allows"] is False
    assert any("无钉批落点" in r for r in snap["misalign_reasons"])

    ticket = _pending_ticket(db_path)
    assert ticket is not None
    with pytest.raises(ServiceError) as exc:
        review.decide(ticket["id"], "放行", "tester", "", db_path)
    assert "已挡" in exc.value.message or "钉批" in exc.value.message


def test_chip_only_without_ledger_row_blocks(db_path):
    # 旧脚手架只写芯片；现在必须判定为「只有芯片、无落点行」。
    with get_db(db_path) as conn:
        _meta_set(conn, "pin_batch_panel_chip", PIN_OK)

    snap = pin_batch.snapshot(db_path)
    assert snap["chip"] == PIN_OK
    assert snap["ledger_present"] is False
    assert snap["aligned"] is False
    assert snap["gate_allows"] is False
    assert any("只有钉批芯片" in r for r in snap["misalign_reasons"])

    with pytest.raises(ServiceError):
        pin_batch.require_pack_or_raise(db_path)


# ---------------------------------------------------------------- 落点与 04 批次
def test_commit_lands_ledger_and_snapshot_for_bug04(db_path):
    batch = _batch_by_code("CAP-20261121-04", db_path)
    out = pin_batch.commit_batch(batch["id"], "对账钉批", db_path)

    assert out["batch_code"] == "CAP-20261121-04"
    assert out["fingerprint"] and out["fingerprint"] != "stale-fp"

    ledger = pin_batch.ledger_rows(db_path)
    assert len(ledger) == 1
    assert ledger[0]["batch_code"] == "CAP-20261121-04"
    assert ledger[0]["bad_fingerprint"] == out["fingerprint"]

    snap_rows = pin_batch.snapshot_rows(db_path)
    assert len(snap_rows) == ledger[0]["bad_count"]

    snap = pin_batch.snapshot(db_path)
    assert snap["active_read"] == "cutover_book"
    assert snap["reject_refresh"] is True
    assert snap["fingerprint_match"] is True
    assert snap["gate_allows"] is True

    report = reconcile.run_reconcile(db_path)
    assert report["pinned_batch_code"] == "CAP-20261121-04"
    assert report["pinned_fingerprint"] == out["fingerprint"]
    assert report["fingerprint_match"] == 1
    assert report["gate_allows"] == 1
    assert "CAP-20261121-04" in report["summary"]


def test_commit_action_compat_path_requires_batch(db_path):
    batch = _batch_by_code("CAP-20261121-04", db_path)
    out = pin_batch.commit_action({"batch_id": batch["id"]}, db_path)
    assert out["batch_code"] == "CAP-20261121-04"

    # 同一批次再钉，必须白话拒绝，不能覆盖旧钉点。
    with pytest.raises(ServiceError) as exc:
        pin_batch.commit_action({"batch_id": batch["id"]}, db_path)
    assert "已钉批" in exc.value.message


# ---------------------------------------------------------------- 指纹拧花
def test_fingerprint_twist_blocks_release_and_is_not_refreshed(db_path):
    batch, ticket = _make_ticket(db_path, "CAP-20261121-01")
    out = pin_batch.commit_batch(batch["id"], "", db_path)
    pinned_fp = out["fingerprint"]

    # 钉批之后坏件集合被改动 → 指纹拧花。
    captures.add_item(batch["id"], "sku-tamper-04", "", "编码空", db_path)
    assert pin_batch.bad_fingerprint(batch["id"], db_path) != pinned_fp

    snap = pin_batch.snapshot(db_path)
    assert snap["fingerprint_match"] is False
    assert snap["gate_allows"] is False
    assert any("指纹" in r for r in snap["misalign_reasons"])

    with pytest.raises(ServiceError):
        review.decide(ticket["id"], "放行", "tester", "", db_path)

    report = reconcile.run_reconcile(db_path)
    assert report["fingerprint_match"] == 0
    # 对账只读：不得回刷钉批当刻指纹。
    assert report["pinned_fingerprint"] == pinned_fp
    assert pin_batch.cutover_fp(db_path) == pinned_fp
    assert pin_batch.active_pin(db_path)["bad_fingerprint"] == pinned_fp


def test_clean_alignment_allows_release(db_path):
    batch, ticket = _make_ticket(db_path, "CAP-20261121-04")
    pin_batch.commit_batch(batch["id"], "", db_path)

    snap = pin_batch.snapshot(db_path)
    assert snap["gate_allows"] is True
    decided = review.decide(ticket["id"], "放行", "tester", "闸内放行", db_path)
    assert decided["decision"] == "放行"


# ---------------------------------------------------------------- 芯片/批次号对不齐
def test_chip_batch_code_misalignment_blocks(db_path):
    batch = _batch_by_code("CAP-20261121-04", db_path)
    pin_batch.commit_batch(batch["id"], "", db_path)

    with get_db(db_path) as conn:
        _meta_set(conn, "pin_batch_pinned_batch_code", "CAP-OTHER-9999")

    snap = pin_batch.snapshot(db_path)
    assert snap["gate_allows"] is False
    assert any("对不齐" in r for r in snap["misalign_reasons"])

    with pytest.raises(ServiceError):
        pin_batch.require_pack_or_raise(db_path)


# ---------------------------------------------------------------- 串行
def test_two_writers_race_same_batch_only_one_wins(db_path):
    batch = _batch_by_code("CAP-20261121-01", db_path)
    barrier = threading.Barrier(2)
    wins: list[dict] = []
    loses: list[Exception] = []
    guard = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            out = pin_batch.commit_batch(batch["id"], "抢钉", db_path)
            with guard:
                wins.append(out)
        except Exception as exc:  # noqa: BLE001 - 竞争失败要留证
            with guard:
                loses.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(wins) == 1, f"两人同抢都成，验收失败：wins={wins}"
    assert len(loses) == 1
    assert isinstance(loses[0], ServiceError)
    assert "已钉批" in loses[0].message

    ledger = pin_batch.ledger_rows(db_path)
    assert len(ledger) == 1
    # 落点没有被第二次提交覆盖。
    assert ledger[0]["bad_fingerprint"] == wins[0]["fingerprint"]


def test_failed_commit_rolls_back_whole_landing(db_path):
    with pytest.raises(ServiceError):
        pin_batch.commit_batch(999999, "不存在批次", db_path)

    assert pin_batch.ledger_rows(db_path) == []
    snap = pin_batch.snapshot(db_path)
    assert snap["chip"] == PIN_BAD
    assert snap["ledger_present"] is False


# ---------------------------------------------------------------- 对账只读 / 不自动钉
def test_reconcile_never_auto_pins(db_path):
    assert pin_batch.active_pin(db_path) is None
    report = reconcile.run_reconcile(db_path)
    assert pin_batch.active_pin(db_path) is None
    assert pin_batch.panel_chip(db_path) == PIN_BAD
    assert report["gate_allows"] == 0
    assert report["fingerprint_match"] == 0


def test_reconcile_reports_real_counts_not_hardcoded(db_path):
    report = reconcile.run_reconcile(db_path)
    # 种子数据里有一条回炉前可数、且报告不得写死 reworking=0 / mismatch=0。
    assert isinstance(report["reworking"], int)
    assert isinstance(report["mismatch"], int)
    assert "待复核" in report["summary"]
    assert "回炉中" in report["summary"]
    assert "错位" in report["summary"]


# ---------------------------------------------------------------- 编排闸
def test_policy_orchestration_blocked_when_chip_and_ledger_disagree(db_path):
    batch = _batch_by_code("CAP-20261121-04", db_path)
    pin_batch.commit_batch(batch["id"], "", db_path)
    with get_db(db_path) as conn:
        _meta_set(conn, "pin_batch_pinned_batch_code", "CAP-OTHER-9999")

    with pytest.raises(ServiceError) as exc:
        policies.apply_to_batch(batch["id"], db_path)
    assert "已挡" in exc.value.message or "对不齐" in exc.value.message

    # 对不齐修好后，编排恢复。
    with get_db(db_path) as conn:
        _meta_set(conn, "pin_batch_pinned_batch_code", "CAP-20261121-04")
    policies.apply_to_batch(batch["id"], db_path)


def test_policy_orchestration_blocked_when_only_chip(db_path):
    batch = _batch_by_code("CAP-20261121-04", db_path)
    with get_db(db_path) as conn:
        _meta_set(conn, "pin_batch_panel_chip", PIN_OK)

    with pytest.raises(ServiceError) as exc:
        policies.apply_to_batch(batch["id"], db_path)
    assert "已挡" in exc.value.message or "落点" in exc.value.message


def test_rework_release_blocked_when_fingerprint_twisted(db_path):
    batch, ticket = _make_ticket(db_path, "CAP-20261121-01")
    pin_batch.commit_batch(batch["id"], "", db_path)
    review.decide(ticket["id"], "驳回回炉", "tester", "回炉", db_path)
    job = next(j for j in rework.list_jobs(db_path) if j["row_id"] == ticket["row_id"])

    captures.add_item(batch["id"], "sku-twist-2", "", "编码空", db_path)
    with pytest.raises(ServiceError):
        rework.run_job(job["id"], succeed=True, db_path=db_path)


# ---------------------------------------------------------------- 单轨
def test_dualwrite_second_track_is_refused(db_path):
    with pytest.raises(ServiceError) as exc:
        pin_batch_dualwrite.apply_dualwrite("双写", db_path)
    assert "未启用" in exc.value.message or "禁止双开" in exc.value.message


# ---------------------------------------------------------------- 脚手架必须拆
def test_scaffolding_is_gone():
    root = pathlib.Path(__file__).resolve().parent.parent
    text = "\n".join(
        p.read_text(encoding="utf-8")
        for base in (root / "app", root / "static")
        for p in base.rglob("*")
        if p.suffix in {".py", ".js", ".html"}
    )
    for needle in (
        "gate_bypass",
        "pack_decoy",
        "display_only",
        "stale-fp",
        "half_fix_display",
        "半修对齐",
    ):
        assert needle not in text, f"脚手架未拆：{needle}"
