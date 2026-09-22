"""给数字义体注入故障：把真机上踩过的坑，在没有真机时按需复现一次。

为什么需要：Ghost 的价值不在一切顺利的时候，而在设备出问题的时候——
腿板掉线、串口断开、被扳倒触发急停。这些在真机上要么靠运气撞见，要么要动手拔线，
没法在评委面前稳定复现。义体上一条命令就能演一遍，而且每次都一模一样。

本文件**无线程、无 IO、无 time.time()**：时间由调用方传进来，
所以同一段注入脚本回放两次，事件序列逐帧相同（和 fly-reflex 一个路子）。

故障种类与真机现象的对应关系：

    legs_offline  腿板掉线：串口还在出帧，但四个关节字段恒为 0
    port_lost     串口断开：整段没有帧，bridge 会走 stall → 重连
    tilt          被扳倒：腰部 pitch 拉到阈值以上，触发反射层急停
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .protocol import Sample

__all__ = ["FAULT_KINDS", "Fault", "FaultInjector"]

#: 故障名 -> 一句话说明，给 `ctl fault --help` 和仪表盘用。
FAULT_KINDS = {
    "legs_offline": "腿板掉线：关节数据恒为 0，结束后自动上线（含 15 秒静默期）",
    "port_lost": "串口断开：整段不出帧，触发数据流中断与自动重连",
    "tilt": "被扳倒：腰部 pitch 拉到 60°，触发反射层急停",
}

TILT_DEG = 60.0          # 超过穿戴档的 45° 阈值，但远不到侧躺的 75°


@dataclass
class Fault:
    """一次注入：从 `start` 开始，持续 `duration_s` 秒。"""
    kind: str
    start: float
    duration_s: float
    magnitude: float = TILT_DEG
    _entered: bool = field(default=False, repr=False)

    def active(self, now: float) -> bool:
        return self.start <= now < self.start + self.duration_s

    def done(self, now: float) -> bool:
        return now >= self.start + self.duration_s


class FaultInjector:
    """排队若干次注入，每帧问它一次。没有排队的故障时开销近似为零。"""

    def __init__(self) -> None:
        self.queue: list[Fault] = []
        self.active: Optional[Fault] = None
        self.n_injected = 0

    def arm(self, kind: str, *, now: float, delay_s: float = 0.0,
            duration_s: float = 6.0, magnitude: float = TILT_DEG) -> Fault:
        if kind not in FAULT_KINDS:
            raise ValueError(f"未知故障 {kind!r}，可用：{sorted(FAULT_KINDS)}")
        f = Fault(kind=kind, start=now + delay_s, duration_s=duration_s, magnitude=magnitude)
        self.queue.append(f)
        return f

    def clear(self) -> None:
        self.queue.clear()
        self.active = None

    def step(self, now: float, s: Sample) -> tuple[Optional[Sample], list[str]]:
        """返回 (这一帧应该发出去的样本，要广播的事件)。样本为 None 表示这一帧丢掉。

        丢帧是故意的：`port_lost` 就是要让上层自己发现数据流停了。
        """
        events: list[str] = []
        f = self.active
        if f is None:
            for cand in self.queue:
                if cand.active(now):
                    f = self.active = cand
                    break
        if f is None:
            self.queue = [c for c in self.queue if not c.done(now)]
            return s, events

        if not f._entered:
            f._entered = True
            self.n_injected += 1
            if f.kind == "legs_offline":
                events.append("legs_offline")
            elif f.kind == "port_lost":
                events.append("stall")

        if f.done(now):
            self.active = None
            self.queue = [c for c in self.queue if c is not f]
            if f.kind == "legs_offline":
                events.append("legs_online")
            elif f.kind == "port_lost":
                events.append("reconnected")
            return s, events

        if f.kind == "legs_offline":
            return replace(s, ldeg=0.0, rdeg=0.0, ldps=0.0, rdps=0.0), events
        if f.kind == "port_lost":
            return None, events
        if f.kind == "tilt":
            return replace(s, pitch=f.magnitude), events
        return s, events
