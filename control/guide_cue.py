"""Short, table-only motor cue for the supervised glasses demonstration.

This is a timed relative hold, not a walking or steering controller.  It
returns zero torque by itself when the deadline passes, even if the service
main loop is delayed.
"""
from __future__ import annotations

import time
import math

from .policies import HoldPolicy, UP_SIGN

CUE_ANGLE_DEG = 20.0
CUE_MAX_NM = 0.5
CUE_SLEW_DPS = 10.0
CUE_SECONDS = 4.0
UP_SOFT_LIMIT_DEG = {"L": -80.0, "R": 80.0}


class GuideCuePolicy:
    name = "guide_cue"
    gain = 0.0
    max_torque = CUE_MAX_NM
    ramp_nm_per_s = 1.0

    def __init__(self, direction: str, left_deg: float, right_deg: float, *,
                 clock=time.monotonic):
        if direction not in {"left", "right"}:
            raise ValueError("演示方向只能是 left 或 right")
        self.direction = direction
        self.leg = "L" if direction == "right" else "R"
        start = left_deg if self.leg == "L" else right_deg
        if not math.isfinite(start):
            raise ValueError("关节角度无效")
        self.target_deg = start + UP_SIGN[self.leg] * CUE_ANGLE_DEG
        if (self.leg == "L" and self.target_deg < UP_SOFT_LIMIT_DEG["L"] or
                self.leg == "R" and self.target_deg > UP_SOFT_LIMIT_DEG["R"]):
            raise ValueError("抬腿目标接近行程末端，本次不动作")
        self._clock = clock
        self.until = clock() + CUE_SECONDS
        self._hold = HoldPolicy(kp=0.04, kd=0.006, ki=0.0,
                                max_torque=CUE_MAX_NM, slew_dps=CUE_SLEW_DPS)
        self._hold.set_target(self.leg, self.target_deg)

    def expired(self) -> bool:
        return self._clock() >= self.until

    def torque(self, sample, scale: float = 1.0) -> tuple[float, float]:
        if self.expired():
            return 0.0, 0.0
        return self._hold.torque(sample, scale)

    def status(self) -> str:
        return f"{self.direction} -> {self.leg} 抬腿，剩余 {max(0, self.until - self._clock()):.1f}s"
