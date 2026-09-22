"""把会话流水 + 传感器 CSV 汇总成交付单需要的那些数字。

**纯函数**：输入是两个列表，输出是一个 dict，不读文件、不碰时间。
读文件的事在 `tools/report.py` 里做。

原则：每一条结论都要能指回证据——流水的第几条、CSV 的哪一段。
算不出来的就写"没有数据"，不要编。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from bridge.protocol import DPS_SATURATION

__all__ = ["collect", "summarise_stream"]


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def summarise_stream(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """从传感器 CSV 里算出这次会话的实测包络。行数为 0 时如实说没有数据。"""
    if not rows:
        return {"n": 0, "note": "没有传感器数据"}
    t = [_f(r.get("host_t")) for r in rows]
    span = max(t[-1] - t[0], 1e-9)
    ldeg = [_f(r.get("ldeg")) for r in rows]
    rdeg = [_f(r.get("rdeg")) for r in rows]
    dps = [x for r in rows for x in (_f(r.get("ldps")), _f(r.get("rdps")))]
    good = [x for x in dps if abs(x) < DPS_SATURATION]
    taul = [_f(r.get("cmd_l")) for r in rows]
    taur = [_f(r.get("cmd_r")) for r in rows]
    # 做功：τ·ω·dt，饱和帧跳过（速度不可信）
    work = 0.0
    for i in range(1, len(rows)):
        dt = t[i] - t[i - 1]
        if dt <= 0 or dt > 0.1:
            continue
        wl, wr = _f(rows[i].get("ldps")), _f(rows[i].get("rdps"))
        if abs(wl) >= DPS_SATURATION or abs(wr) >= DPS_SATURATION:
            continue
        work += (taul[i] * math.radians(wl) + taur[i] * math.radians(wr)) * dt
    gaps = [t[i] - t[i - 1] for i in range(1, len(t))]
    return {
        "n": len(rows),
        "span_s": round(span, 2),
        "hz_mean": round(len(rows) / span, 1),
        "gap_max_ms": round(max(gaps) * 1000, 1) if gaps else 0.0,
        "ldeg_range": [round(min(ldeg), 1), round(max(ldeg), 1)],
        "rdeg_range": [round(min(rdeg), 1), round(max(rdeg), 1)],
        "dps_peak": round(max((abs(x) for x in good), default=0.0), 1),
        "saturated_frames": sum(1 for x in dps if abs(x) >= DPS_SATURATION),
        "tau_peak": round(max((abs(x) for x in taul + taur), default=0.0), 3),
        "work_J": round(work, 3),
    }


def _by(records: Iterable[Mapping[str, Any]], kind: str) -> list[dict]:
    return [dict(r) for r in records if r.get("kind") == kind]


def collect(records: Sequence[Mapping[str, Any]],
            rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """汇总成交付单的骨架。records 是流水，rows 是传感器 CSV。"""
    sessions = _by(records, "session")
    start = next((r for r in sessions if r.get("phase") == "start"), {})
    end = next((r for r in sessions if r.get("phase") == "end"), {})
    events = _by(records, "event")
    recalls = _by(records, "recall")
    decisions = _by(records, "decision")
    commands = _by(records, "command")

    # 把"事件 → 紧随其后的回忆"配对：这就是"Ghost 自己处理异常"的证据
    handled: list[dict] = []
    for ev in events:
        follow = [r for r in recalls if 0 <= r["t"] - ev["t"] <= 3.0]
        handled.append({
            "t": ev["t"], "event": ev.get("event", ""), "msg": ev.get("msg", ""),
            "level": ev.get("level", "info"),
            "recall": follow[0].get("recall") if follow else None,
        })

    # 人为注入的故障要单独列出来：读交付单的人必须知道哪些"异常"是我们自己制造的
    injected = [{"t": c["t"], "kind": c.get("cmd", {}).get("kind", "?"),
                 "seconds": c.get("cmd", {}).get("seconds")}
                for c in commands if c.get("cmd", {}).get("op") == "fault"]
    gaits = [{"t": c["t"], "name": c.get("cmd", {}).get("name")}
             for c in commands if c.get("cmd", {}).get("op") == "gait"]

    ds = [d.get("decision", {}) for d in decisions if d.get("decision")]
    switches = [c for c in commands if c.get("cmd", {}).get("op") == "policy"]
    by_who: dict[str, int] = {}
    for c in commands:
        by_who[c.get("by", "?")] = by_who.get(c.get("by", "?"), 0) + 1

    # 失败归因：明确写出哪些事没成、为什么。空着比编好。
    problems: list[dict] = []
    if end.get("tripped"):
        problems.append({"what": "会话以急停锁存结束", "why": str(end["tripped"]),
                         "evidence": "见下方事件时间线里最后一条 err"})
    if _f(end.get("reconnects")) > 0:
        problems.append({"what": f"串口重连 {int(_f(end['reconnects']))} 次",
                         "why": "数据流中断触发自动重连（力矩已先清零）",
                         "evidence": "事件时间线里的「数据流中断／已重连」"})
    held = [d for d in ds if d.get("held")]
    if held:
        by_reason: dict[str, int] = {}
        for d in held:
            by_reason[d.get("held_by", "?")] = by_reason.get(d.get("held_by", "?"), 0) + 1
        problems.append({
            "what": f"{len(held)} 次判断没有被采纳",
            "why": "、".join(f"{'置信度不足' if k == 'gate' else '防抖期内'} {v} 次"
                             for k, v in sorted(by_reason.items())),
            "evidence": "这是设计如此：不确定就不动，不是故障",
        })
    stream = summarise_stream(rows)
    if stream.get("gap_max_ms", 0) > 200:
        why = ("人为注入的 port_lost 故障，是演示的一部分" if any(
            i["kind"] == "port_lost" for i in injected) else "数据流中断，原因见事件时间线")
        problems.append({"what": f"数据流最大间隔 {stream['gap_max_ms']:.0f} ms",
                         "why": why, "evidence": "间隔期间力矩已清零，恢复后重新 ENABLE"})
    if stream.get("saturated_frames"):
        problems.append({
            "what": f"{stream['saturated_frames']} 个关节速度读数饱和（±{DPS_SATURATION} °/s）",
            "why": "传感器量程上限，不是真的转这么快",
            "evidence": "这些帧在安全判定和做功统计里都被跳过了",
        })
    no_recall = [h for h in handled if h["recall"] is not None
                 and not h["recall"].get("hits")]
    for h in no_recall:
        problems.append({"what": f"事件「{h['event']}」没查到对应经验",
                         "why": f"库里没有相似度够高的条目"
                                f"（{h['recall'].get('weak', 0)} 条沾边但不够）",
                         "evidence": "值得补一条 Capsule 进去"})

    conf = [_f(d.get("confidence")) for d in ds]
    return {
        "start": start, "end": end,
        "stream": stream,
        "events": handled,
        "decisions": ds,
        "decision_stats": {
            "n": len(ds),
            "held": len(held),
            "applied": sum(1 for d in ds if d.get("autopilot")),
            "conf_mean": round(sum(conf) / len(conf), 3) if conf else None,
            "conf_min": round(min(conf), 3) if conf else None,
            "conf_max": round(max(conf), 3) if conf else None,
            "wants": _tally(d.get("want") for d in ds),
        },
        "commands": {"n": len(commands), "by": by_who, "policy_switches": len(switches)},
        "injected": injected, "gaits": gaits,
        "recalls": [r.get("recall") for r in recalls if r.get("recall")],
        "problems": problems,
    }


def _tally(xs: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        if x is None:
            continue
        out[str(x)] = out.get(str(x), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
