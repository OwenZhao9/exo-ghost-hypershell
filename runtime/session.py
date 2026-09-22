"""会话状态：一次服务运行期间会变的那些东西。

原来这些散在 `main()` 的一个 dict 里，谁都能改、改了也看不出来。
收成一个对象后，命令、事件、主循环三方都通过它交流，改动有据可查。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import control.policies as P
from control.safety import SafetyProfile, SafetyMonitor

WEARING_RAMP_CAP_NM_S = 1.5      # 穿戴档的斜坡上限，再乘 0.5
WEARING_RAMP_FACTOR = 0.5


@dataclass
class Session:
    profile: SafetyProfile
    ramp_cap_nm_s: float                      # 命令行 --ramp 给的全局上限
    policy: Any = None
    monitor: Optional[SafetyMonitor] = None
    memory: Optional[Any] = None          # agent.memory.GhostMemory；没接经验层时为 None
    armed: bool = True
    seq: int = 0                              # 已处理到的命令序号
    pulse_until: float = 0.0                  # keepalive 脉冲的截止时刻
    last_motion: float = field(default_factory=time.time)
    legs_online_at: Optional[float] = None    # 腿板上线时刻，用于静默期

    def __post_init__(self) -> None:
        if self.policy is None:
            self.policy = P.make_policy("zero", 0.0, 1.5)
        if self.monitor is None:
            self.monitor = SafetyMonitor(self.profile)

    # ---------- 斜坡 ----------
    def ramp_for_current_policy(self) -> float:
        """项目规则第 1 条：任何力都要慢慢加。穿戴档在策略斜坡基础上再减半。"""
        r = getattr(self.policy, "ramp_nm_per_s", 3.0)
        if self.profile.name == "wearing":
            r = min(r, WEARING_RAMP_CAP_NM_S) * WEARING_RAMP_FACTOR
        return min(r, self.ramp_cap_nm_s)

    def apply_ramp(self, bridge) -> None:
        bridge.set_ramp(self.ramp_for_current_policy())

    # ---------- 静默期 ----------
    def in_quiet_period(self, now: float, quiet_s: float) -> bool:
        return self.legs_online_at is not None and now - self.legs_online_at < quiet_s
