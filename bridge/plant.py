"""被控对象（plant）：关节上挂的那条腿。

`sim2real_actuator` 只管**执行器**（摩擦、偏置、回差、限幅）；
腿有多重、重心在哪、撞到哪里停——那是**被控对象**，是本项目特有的，
所以留在这里，不进通用库。换一台机器只要换这个文件。

参数来自真机实测（见 docs/protocol.md）：关节量程约 −108°…+105°。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DEG2RAD = math.pi / 180.0


@dataclass(frozen=True)
class LegLoad:
    """单条腿的负载模型：重力矩 + 行程末端的硬限位。"""

    gravity_nm: float = 1.2        # 水平伸出时的重力矩（量级由「向下只能压到 ±64°」反推）
    neutral_rad: float = 0.0       # 重力矩为零的姿态
    min_rad: float = -108.0 * DEG2RAD
    max_rad: float = 105.0 * DEG2RAD
    stop_stiffness_nm_per_rad: float = 60.0    # 限位当成硬弹簧
    stop_damping_nm_s_per_rad: float = 2.0

    def external_nm(self, pos_rad: float, vel_rad_s: float) -> float:
        """作用在关节上的外力矩（不含执行器自己的摩擦与偏置）。"""
        tau = -self.gravity_nm * math.sin(pos_rad - self.neutral_rad)
        if pos_rad > self.max_rad:
            over = pos_rad - self.max_rad
            tau -= self.stop_stiffness_nm_per_rad * over + self.stop_damping_nm_s_per_rad * max(vel_rad_s, 0.0)
        elif pos_rad < self.min_rad:
            over = self.min_rad - pos_rad
            tau += self.stop_stiffness_nm_per_rad * over - self.stop_damping_nm_s_per_rad * min(vel_rad_s, 0.0)
        return tau

    def clamp(self, pos_rad: float, vel_rad_s: float) -> tuple[float, float]:
        """越过限位就吸附回去并把速度归零，避免数值上穿出去。"""
        if pos_rad > self.max_rad:
            return self.max_rad, min(vel_rad_s, 0.0)
        if pos_rad < self.min_rad:
            return self.min_rad, max(vel_rad_s, 0.0)
        return pos_rad, vel_rad_s
