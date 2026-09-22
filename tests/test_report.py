"""会话交付单：汇总是纯的，排版不编数据，缺数据要如实说缺。"""
from __future__ import annotations

import json
import time

import pytest

from bridge.protocol import DPS_SATURATION
from report.collect import collect, summarise_stream
from report.render import render
from runtime.journal import Journal, read_journal

T0 = 1_790_000_000.0


def row(i, ldps=10.0, rdps=-10.0, cmd_l=0.0, cmd_r=0.0):
    return {"host_t": T0 + i / 180.0, "ms": i * 5.55, "pitch": 0, "roll": 0, "yaw": 0,
            "gx": 0, "gy": 0, "gz": 0, "ax": 0, "ay": 0, "az": 1, "kpa": 101,
            "ldeg": 5.0 + i * 0.01, "rdeg": -5.0, "ldps": ldps, "rdps": rdps,
            "cmd_l": cmd_l, "cmd_r": cmd_r}


def journal_records():
    return [
        {"t": T0, "kind": "session", "phase": "start", "profile": "table",
         "body": "sim", "limit": 2.0, "version": "sim"},
        {"t": T0 + 1, "kind": "command", "by": "cli",
         "cmd": {"op": "fault", "kind": "legs_offline", "seconds": 4}},
        {"t": T0 + 1.1, "kind": "event", "event": "legs_offline", "level": "warn",
         "msg": "腿板掉线"},
        {"t": T0 + 1.3, "kind": "recall",
         "recall": {"query": "腿板掉线", "weak": 0,
                    "hits": [{"id": "x", "title": "恢复步骤", "score": 0.88,
                              "why": "title~…", "source": "sqlite",
                              "steps": ["先清零", "短按+长按"]}]}},
        {"t": T0 + 2, "kind": "decision",
         "decision": {"t": T0 + 2, "want": "assist", "applied": "zero",
                      "confidence": 0.3, "probs": {"zero": .5, "assist": .5},
                      "gain": 0.1, "backend": "rules", "degraded": True,
                      "held": True, "held_by": "gate", "autopilot": False,
                      "why": "步态相似度 0.3", "features": {}, "labels": {}}},
        {"t": T0 + 3, "kind": "session", "phase": "end", "frames": 540,
         "work_J": 0.5, "reconnects": 0, "tripped": None},
    ]


# ---------------------------------------------------------------- 纯度与空输入

def test_collect_is_pure():
    recs, rows = journal_records(), [row(i) for i in range(50)]
    assert collect(recs, rows) == collect(recs, rows)


def test_empty_input_says_so_instead_of_inventing():
    d = collect([], [])
    assert d["stream"]["n"] == 0 and "没有" in d["stream"]["note"]
    assert d["decision_stats"]["n"] == 0
    assert d["problems"] == []
    html = render(d)
    assert "没有传感器数据" in html and "没有设备异常" in html


# ---------------------------------------------------------------- 包络

def test_saturated_frames_are_counted_and_excluded_from_peaks():
    rows = [row(i) for i in range(20)] + [row(20, ldps=DPS_SATURATION)]
    s = summarise_stream(rows)
    assert s["saturated_frames"] == 1
    assert s["dps_peak"] == 10.0            # 饱和的那一帧没算进峰值


def test_work_matches_the_hand_computation():
    """τ·ω·dt。给一个常力矩常速度的窗口，结果必须对得上手算。"""
    import math
    n, tau, dps = 181, 0.5, 60.0
    rows = [row(i, ldps=dps, rdps=0.0, cmd_l=tau) for i in range(n)]
    s = summarise_stream(rows)
    expect = tau * math.radians(dps) * (n - 1) / 180.0
    assert s["work_J"] == pytest.approx(expect, abs=5e-4)   # 报告里做功保留三位小数


# ---------------------------------------------------------------- 归因

def test_injected_faults_are_called_out_as_injected():
    d = collect(journal_records(), [row(i) for i in range(50)])
    assert d["injected"] and d["injected"][0]["kind"] == "legs_offline"
    assert "人为注入" in render(d)


def test_gate_holds_are_attributed_but_not_called_a_failure():
    d = collect(journal_records(), [row(i) for i in range(50)])
    p = next(p for p in d["problems"] if "没有被采纳" in p["what"])
    assert "置信度不足" in p["why"]
    assert "设计如此" in p["evidence"]


def test_event_is_paired_with_the_recall_that_followed_it():
    d = collect(journal_records(), [row(i) for i in range(50)])
    ev = d["events"][0]
    assert ev["event"] == "legs_offline"
    assert ev["recall"]["hits"][0]["title"] == "恢复步骤"


def test_a_recall_more_than_3s_later_is_not_credited_to_the_event():
    recs = journal_records()
    for r in recs:
        if r["kind"] == "recall":
            r["t"] = T0 + 99
    d = collect(recs, [])
    assert d["events"][0]["recall"] is None


# ---------------------------------------------------------------- 排版

def test_render_escapes_hostile_text():
    recs = journal_records()
    recs[2]["msg"] = "<script>alert(1)</script>"
    html = render(collect(recs, []))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_has_no_external_resources():
    """展位可能没有网，页面必须离线可看。"""
    html = render(collect(journal_records(), [row(i) for i in range(50)]))
    for bad in ("http://", "https://", "<img", "src="):
        assert bad not in html, f"页面引用了外部资源：{bad}"


def test_render_is_deterministic_for_the_same_input():
    d = collect(journal_records(), [row(i) for i in range(50)])
    assert render(d, generated_at=T0) == render(d, generated_at=T0)


# ---------------------------------------------------------------- 流水

def test_journal_roundtrip(tmp_path):
    p = tmp_path / "s.jsonl"
    j = Journal(str(p))
    j.write("event", event="legs_offline", msg="掉线")
    j.write("note", msg="中文与 emoji 🙂 都要能写进去")
    got = read_journal(str(p))
    assert [r["kind"] for r in got] == ["event", "note"]
    assert got[1]["msg"].endswith("🙂 都要能写进去")
    assert all(isinstance(r["t"], float) for r in got)


def test_journal_without_a_path_is_a_no_op():
    j = Journal()
    j.write("event", msg="不该炸")
    assert j.n == 0


def test_broken_lines_are_skipped_not_fatal(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"t":1,"kind":"note"}\n{半截\n{"t":2,"kind":"event"}\n', encoding="utf-8")
    assert [r["kind"] for r in read_journal(str(p))] == ["note", "event"]


def test_journal_write_never_raises(tmp_path):
    """流水写不进去也不许影响控制。"""
    j = Journal(str(tmp_path / "s.jsonl"))
    j.path = str(tmp_path / "没有这个目录" / "s.jsonl")
    j.write("note", msg="x")            # 不抛异常就算通过
    j.write("note", obj=object())       # 不可序列化的东西也不许炸
