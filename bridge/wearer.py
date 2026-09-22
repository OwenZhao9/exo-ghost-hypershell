"""数字义体上的"穿戴者"：一段给定的步态轨迹。

没有它的时候，义体只是一条挂着的腿（重力 + 摩擦 + 我们的力矩），
永远走不了路，直觉层就永远只能判"静止"。有了它才能在没有真人的情况下
把"人在走 → Ghost 认出步态 → 切到助力"这条链路完整跑一遍。

**这是运动学模型，不是动力学模型**，而且这个简化是有意的：
人腿的力矩比这台髋关节外骨骼大一个数量级（人 ~100 Nm，设备硬上限 7.5 Nm），
所以在"人主动走路"这个工况下，是人决定轨迹、设备只能帮一把或拖后腿。
于是这里直接规定关节角轨迹，我们下发的力矩照常记录、照常算做功，
但不改变轨迹。要研究设备力矩如何改变步态，得换成带人体动力学的模型，
那超出这台设备能验证的范围。

纯函数，不碰时间——时间由调用方传进来。
"""
from __future__ import annotations

import math

__all__ = ["GAITS", "Gait", "angles"]

RAD = math.pi / 180.0


class Gait:
    """一种步态：步频、摆幅、左右相位差。"""

    __slots__ = ("name", "hz", "amp_deg", "phase_deg", "note")

    def __init__(self, name: str, hz: float, amp_deg: float,
                 phase_deg: float = 180.0, note: str = "") -> None:
        self.name = name
        self.hz = hz
        self.amp_deg = amp_deg
        self.phase_deg = phase_deg
        self.note = note


#: 三种预设。数值取自常见步态文献里的髋关节范围（慢走 ±15°，正常 ±20~25°）。
GAITS = {
    "slow": Gait("slow", 0.7, 15.0, 180.0, "慢走：步频 0.7 Hz、髋关节 ±15°"),
    "walk": Gait("walk", 1.0, 22.0, 180.0, "正常步行：步频 1.0 Hz、髋关节 ±22°"),
    "fast": Gait("fast", 1.5, 28.0, 180.0, "快走：步频 1.5 Hz、髋关节 ±28°"),
    "limp": Gait("limp", 0.9, 20.0, 110.0, "跛行：左右相位差只有 110°，步态不对称"),
}


def angles(g: Gait, t: float) -> dict[str, tuple[float, float]]:
    """返回 {"L": (角度 rad, 角速度 rad/s), "R": ...}。

    左右腿用同一个正弦，差一个相位；`limp` 把相位差改小，用来检验
    直觉层是不是真的在看"两腿反相"而不是只看摆幅。
    """
    w = 2.0 * math.pi * g.hz
    a = g.amp_deg * RAD
    out = {}
    for leg, ph in (("L", 0.0), ("R", g.phase_deg * RAD)):
        out[leg] = (a * math.sin(w * t + ph), a * w * math.cos(w * t + ph))
    return out
