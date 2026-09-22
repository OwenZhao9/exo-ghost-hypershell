"""安全闸的纯计算部分：限幅与斜坡。

**纯函数，无状态**。项目规则第 1 条：任何力都必须慢慢加——
`ramp_step` 决定"每个发送周期最多变多少"，是那条规则在代码里的落点。
"""
from __future__ import annotations

from .protocol import FIRMWARE_LIMIT_NM

MIN_RAMP_NM_PER_S = 0.05     # 斜坡下限，防止传 0 把力矩冻住


def clamp(value: float, limit: float) -> float:
    """把力矩截断到 ±limit。"""
    return max(-limit, min(limit, float(value)))


def effective_limit(requested: float) -> float:
    """软限幅不得超过固件硬限。"""
    return min(abs(requested), FIRMWARE_LIMIT_NM)


def ramp_step(nm_per_s: float, send_period_s: float) -> float:
    """每个发送周期允许的最大力矩变化量。"""
    return max(MIN_RAMP_NM_PER_S, float(nm_per_s)) * send_period_s


def step_toward(current: float, target: float, max_delta: float) -> float:
    """把 current 朝 target 推进不超过 max_delta。"""
    return current + max(-max_delta, min(max_delta, target - current))
