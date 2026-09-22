"""从一小段数据窗口里，算出几个人能读懂的动作特征。

**纯函数，无状态，不碰时间**：同一段窗口算两次结果完全一样，所以决策可以回放复现。

为什么不直接把原始帧丢给决策层：540 帧 × 16 个字段没人看得懂，也没法写进日志。
这里先压成十来个有名字的量（步频、两腿是不是反相、幅度、峰值速度……），
决策层只看这些量，仪表盘上也直接显示这些量——Ghost 凭什么这么判，人能自己核对。
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from bridge.protocol import DPS_SATURATION, Sample

__all__ = ["FEATURE_LABELS", "STILL_DPS", "extract"]

STILL_DPS = 8.0          # 低于这个角速度算"没在动"（实测静止时噪声 < 3 °/s）
_MIN_FRAMES = 20         # 少于这么多帧不做判断，宁可说不知道

#: 特征名 -> 中文标签，仪表盘直接用这张表，不在前端硬编码。
FEATURE_LABELS = {
    "hz": "数据率 Hz",
    "still_frac": "静止占比",
    "cadence_hz": "步频 Hz",
    "antiphase": "两腿反相程度",
    "rom_deg": "摆动幅度 °",
    "mean_dps": "平均角速度 °/s",
    "peak_dps": "峰值角速度 °/s",
    "tilt_deg": "最大倾角 °",
}


def _finite(xs: Sequence[float]) -> list[float]:
    """丢掉饱和帧：±3276.7 是传感器上限，不是真的转这么快。"""
    return [x for x in xs if abs(x) < DPS_SATURATION]


def _zero_crossings(xs: Sequence[float], dead: float) -> int:
    """符号翻转次数，带死区——噪声在 0 附近来回抖不算一次跨越。"""
    n = 0
    sign = 0
    for x in xs:
        if x > dead:
            s = 1
        elif x < -dead:
            s = -1
        else:
            continue          # 死区里不改变当前符号
        if sign and s != sign:
            n += 1
        sign = s
    return n


def _corr(a: Sequence[float], b: Sequence[float]) -> float:
    """皮尔逊相关系数，两条都没波动时返回 0（而不是除零）。"""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    va = math.fsum((x - ma) ** 2 for x in a[:n])
    vb = math.fsum((x - mb) ** 2 for x in b[:n])
    if va <= 0.0 or vb <= 0.0:
        return 0.0
    cov = math.fsum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return max(-1.0, min(1.0, cov / math.sqrt(va * vb)))


def extract(window: Sequence[Sample]) -> dict[str, Any]:
    """把一段样本压成特征字典。帧太少时 `usable=False`，决策层据此说"不知道"。"""
    n = len(window)
    if n < _MIN_FRAMES:
        return {"usable": False, "n": n, "reason": f"窗口只有 {n} 帧，不足 {_MIN_FRAMES}"}

    span = max(window[-1].host_t - window[0].host_t, 1e-6)
    ldps = _finite([s.ldps for s in window])
    rdps = _finite([s.rdps for s in window])
    if len(ldps) < _MIN_FRAMES or len(rdps) < _MIN_FRAMES:
        return {"usable": False, "n": n, "reason": "窗口里大部分是饱和帧"}

    both = [(abs(l) + abs(r)) / 2.0 for l, r in zip(ldps, rdps)]
    ldeg = [s.ldeg for s in window]
    rdeg = [s.rdeg for s in window]
    # 步频：一条腿前后摆一个来回 = 两次过零
    crossings = _zero_crossings(ldps, STILL_DPS * 2)
    return {
        "usable": True,
        "n": n,
        "span_s": round(span, 3),
        "hz": round(n / span, 1),
        "still_frac": round(sum(1 for x in both if x < STILL_DPS) / len(both), 3),
        "cadence_hz": round(crossings / 2.0 / span, 3),
        "antiphase": round(-_corr(ldps, rdps), 3),      # 走路时两腿反相 → 相关为负 → 这里为正
        "rom_deg": round(max(max(ldeg) - min(ldeg), max(rdeg) - min(rdeg)), 1),
        "mean_dps": round(sum(both) / len(both), 1),
        "peak_dps": round(max(both), 1),
        "tilt_deg": round(max(max(abs(s.pitch), abs(s.roll)) for s in window), 1),
    }
