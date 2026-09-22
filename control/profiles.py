"""安全档位：纯数据，不含任何判定逻辑。

`table` 是设备放桌上/支架上调试用的宽松档；`wearing` 是穿在人身上时用的收紧档。
阈值改动一律在这里发生，判定怎么做由 `control/reflex_rules.py` 翻译成规则。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = ["SafetyProfile", "TABLE", "WEARING", "PROFILES"]


@dataclass
class SafetyProfile:
    name: str
    # 急停阈值
    acc_trip_g: float            # 腰部加速度模长（静止 1 g；走路峰值 ~1.5 g；摔倒/撞击 > 2.5 g）
    gyro_trip_dps: float         # 腰部角速度（走路 < 150 °/s；摔倒/急转 > 300）
    tilt_trip_deg: Optional[float]   # |pitch| 或 |roll| 超过即急停；桌面测试设 None（侧躺 ~75°）
    joint_dps_trip: float        # 关节角速度超过即急停（走路 < 300 °/s）
    min_stream_hz: float         # 数据流低于此频率 → 由 bridge 清零重连（不再是急停）
    max_session_s: float         # 硬性会话时长
    # assist 渐弱
    assist_dps_soft: float       # 超过此速度 assist 开始渐弱
    assist_dps_hard: float       # 超过此速度 assist = 0
    assist_angle_soft_deg: float # 偏离中立位超过此角度开始渐弱
    assist_angle_hard_deg: float # 偏离中立位超过此角度 assist = 0
    assist_energy_J_per_s: float # 每秒对腿做的正功预算，超过 → assist = 0 直到回落


TABLE = SafetyProfile(
    name="table", acc_trip_g=3.0, gyro_trip_dps=400.0, tilt_trip_deg=None, joint_dps_trip=2500.0,   # 桌面：支架自由甩动/腿板上线自检会到 1200–1700°/s，只拦饱和级事件
    min_stream_hz=120.0, max_session_s=1800,
    assist_dps_soft=120.0, assist_dps_hard=220.0, assist_angle_soft_deg=40.0, assist_angle_hard_deg=60.0,
    assist_energy_J_per_s=1.5,
)
WEARING = SafetyProfile(
    name="wearing", acc_trip_g=2.5, gyro_trip_dps=300.0, tilt_trip_deg=45.0, joint_dps_trip=450.0,
    min_stream_hz=120.0, max_session_s=600,
    assist_dps_soft=150.0, assist_dps_hard=260.0, assist_angle_soft_deg=45.0, assist_angle_hard_deg=65.0,
    assist_energy_J_per_s=3.0,
)
PROFILES = {"table": TABLE, "wearing": WEARING}
