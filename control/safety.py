"""安全监视器：所有判定都是纯规则，运行在桥接层回调里，不经过 LLM。
两类输出：
  trip(s)   -> 返回非空字符串即急停（力矩清零 + DISABLE，锁存，需重启程序）
  scale(s)  -> 0..1，对 assist（负阻尼）做渐弱：接近速度上限 / 角度边界 / 能量预算时压到 0
"""
from __future__ import annotations
import math, time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from bridge.serial_io import Sample


@dataclass
class SafetyProfile:
    name: str
    # 急停阈值
    acc_trip_g: float            # 腰部加速度模长（静止 1 g；走路峰值 ~1.5 g；摔倒/撞击 > 2.5 g）
    gyro_trip_dps: float         # 腰部角速度（走路 < 150 °/s；摔倒/急转 > 300）
    tilt_trip_deg: Optional[float]   # |pitch| 或 |roll| 超过即急停；桌面测试设 None（侧躺 ~75°）
    joint_dps_trip: float        # 关节角速度超过即急停（走路 < 300 °/s）
    min_stream_hz: float         # 数据流低于此频率 → 急停（速度估计不可信）
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


class SafetyMonitor:
    def __init__(self, profile: SafetyProfile, warmup_s: float = 2.0):
        self.p = profile
        self.t_start: Optional[float] = None
        self.warmup_s = warmup_s
        self.neutral_l: Optional[float] = None
        self.neutral_r: Optional[float] = None
        self._warm_l: list[float] = []; self._warm_r: list[float] = []
        self._times: deque[float] = deque(maxlen=400)
        self._energy: deque[tuple[float, float]] = deque()   # (t, +J) 最近 1 s 的正功
        self._last_t: Optional[float] = None
        self._budget_blown_until = 0.0
        self.last_scale = 1.0
        self.reason: Optional[str] = None
        self._joint_over = {"左": 0, "右": 0}

    def notify_reconnect(self) -> None:
        """串口重连后调用：数据流频率判定重新热身 3 秒"""
        self._times.clear()
        self.t_start = time.time()

    # ---------- 急停判定 ----------
    def trip(self, s: Sample) -> Optional[str]:
        now = s.host_t
        if self.t_start is None:
            self.t_start = now
        self._times.append(now)
        p = self.p
        # 热身阶段只采中立位，不判定动态阈值（刚 ENABLE 时可能有瞬态）
        if now - self.t_start < self.warmup_s:
            self._warm_l.append(s.ldeg); self._warm_r.append(s.rdeg)
            return None
        if self.neutral_l is None:
            self._warm_l.sort(); self._warm_r.sort()
            self.neutral_l = self._warm_l[len(self._warm_l)//2] if self._warm_l else s.ldeg
            self.neutral_r = self._warm_r[len(self._warm_r)//2] if self._warm_r else s.rdeg
        a = math.sqrt(s.ax*s.ax + s.ay*s.ay + s.az*s.az)
        if a > p.acc_trip_g:
            return f"腰部加速度 {a:.1f} g > {p.acc_trip_g} g（撞击/摔倒）"
        g = math.sqrt(s.gx*s.gx + s.gy*s.gy + s.gz*s.gz)
        if g > p.gyro_trip_dps:
            return f"腰部角速度 {g:.0f} °/s > {p.gyro_trip_dps}（急转/摔倒）"
        if p.tilt_trip_deg is not None and (abs(s.pitch) > p.tilt_trip_deg or abs(s.roll) > p.tilt_trip_deg):
            return f"倾角 pitch={s.pitch:.0f} roll={s.roll:.0f} > {p.tilt_trip_deg}°（跌倒）"
        for name, w in (("左", s.ldps), ("右", s.rdps)):
            if abs(w) < 3000 and abs(w) > p.joint_dps_trip:      # 饱和尖峰 3276.7 单独忽略
                self._joint_over[name] += 1
                if self._joint_over[name] >= 3:                  # 连续 3 帧（≈17 ms）才算，单帧毛刺不触发
                    return f"{name}髋角速度 {w:.0f} °/s > {p.joint_dps_trip}"
            else:
                self._joint_over[name] = 0
        if now - self.t_start > p.max_session_s:
            return f"会话超过 {p.max_session_s:.0f} s 上限"
        # 数据流频率不再在这里判定：通信丢失由 bridge 的 supervisor 处理（清零 + 自动重连），不是急停
        return None

    # ---------- assist 渐弱 ----------
    @staticmethod
    def _taper(x: float, soft: float, hard: float) -> float:
        if x <= soft: return 1.0
        if x >= hard: return 0.0
        return 1.0 - (x - soft) / (hard - soft)

    def assist_scale(self, s: Sample, tau_l: float, tau_r: float) -> float:
        """返回 0..1。tau_* 是本帧准备下发的力矩，用来累计正功预算。"""
        p = self.p
        if self.neutral_l is None:
            return 0.0                                      # 热身期间不助力
        wl = 0.0 if abs(s.ldps) > 3000 else s.ldps
        wr = 0.0 if abs(s.rdps) > 3000 else s.rdps
        sc = 1.0
        sc = min(sc, self._taper(abs(wl), p.assist_dps_soft, p.assist_dps_hard))
        sc = min(sc, self._taper(abs(wr), p.assist_dps_soft, p.assist_dps_hard))
        sc = min(sc, self._taper(abs(s.ldeg - self.neutral_l), p.assist_angle_soft_deg, p.assist_angle_hard_deg))
        sc = min(sc, self._taper(abs(s.rdeg - self.neutral_r), p.assist_angle_soft_deg, p.assist_angle_hard_deg))
        # 正功预算（只累计设备对腿做的正功）
        now = s.host_t
        if self._last_t is not None:
            dt = now - self._last_t
            pw = tau_l * math.radians(wl) + tau_r * math.radians(wr)
            if pw > 0: self._energy.append((now, pw * dt))
        self._last_t = now
        while self._energy and now - self._energy[0][0] > 1.0:
            self._energy.popleft()
        e = sum(j for _, j in self._energy)
        if e > p.assist_energy_J_per_s:
            self._budget_blown_until = now + 0.5
        if now < self._budget_blown_until:
            sc = 0.0
        self.last_scale = sc
        return sc
