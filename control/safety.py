"""安全监视器：所有判定都是纯规则，运行在桥接层回调里，不经过 LLM。

两类输出（分工没变）：
  trip(s)   -> 返回非空字符串即"这一帧不安全"。**本层不锁存**，锁存由调用方
               （ExoBridge.trip → 力矩清零 + DISABLE）负责。
  assist_scale(s, τl, τr) -> 0..1，对 assist（负阻尼）做渐弱。

判定内核换成了 [fly-reflex](https://github.com/OwenZhao9/fly-reflex)：
一个受果蝇逃逸反射启发的确定性反射层——时间由调用方传入、不碰 time.time()、
运行期不抛异常，所以同一份录制回放两次结果逐帧一致（回归基准就靠这个）。

这里留下的只有 fly-reflex 明确不管的两件**有状态**的事：

  1. 中立位：热身 2 秒取左右髋角的中位数，之后"偏离中立位多少度"才有意义。
  2. 正功预算：最近 1 秒对腿做了多少正功，超预算就把 assist 压到 0 并冷却 0.5 秒。

契约要求 `derived=` 里的函数无状态，所以这两个量由本文件算好，以普通 key 塞进
每帧的 sensors 字典（`l_dev` / `r_dev` / `session_s`），再交给 fly-reflex 判。
"""
from __future__ import annotations
import math, time
from collections import deque
from typing import Optional

from fly_reflex import Action, Reflex

from bridge.serial_io import Sample
from .profiles import PROFILES, SafetyProfile, TABLE, WEARING
from .reflex_rules import DERIVED, DPS_IGNORE_ABOVE, build_rules, build_tapers

__all__ = ["SafetyProfile", "TABLE", "WEARING", "PROFILES", "SafetyMonitor"]


class SafetyMonitor:
    def __init__(self, profile: SafetyProfile, warmup_s: float = 2.0, backend: str = "rules"):
        """backend="rules" 是逐条阈值；"spiking" 换成 fly-reflex 的脉冲网络后端
        （接口完全一样，需要 numpy）。默认永远是 rules——脉冲后端只用于演示对照。"""
        self.p = profile
        self.t_start: Optional[float] = None
        self.warmup_s = warmup_s
        self.neutral_l: Optional[float] = None
        self.neutral_r: Optional[float] = None
        self.backend = backend
        self._warm_l: list[float] = []; self._warm_r: list[float] = []
        self._times: deque[float] = deque(maxlen=400)
        self._energy: deque[tuple[float, float]] = deque()   # (t, +J) 最近 1 s 的正功
        self._last_t: Optional[float] = None
        self._budget_blown_until = 0.0
        self.last_scale = 1.0
        self.last_detail: dict[str, float] = {}     # 每条渐弱条各自的系数，给界面解释用
        self.last_binding = ""                      # 这一帧是哪条在压着输出
        self.reason: Optional[str] = None
        self.reflex = self._build_reflex()

    def _build_reflex(self) -> Reflex:
        tapers = build_tapers(self.p)
        if self.backend == "spiking":
            return Reflex.spiking(signals=("acc_mag", "gyro_mag", "tilt_deg", "joint_dps"),
                                  ignore_above=DPS_IGNORE_ABOVE, warmup_s=self.warmup_s,
                                  action=Action.SOFT_STOP, tapers=tapers, derived=DERIVED)
        return Reflex.rules(*build_rules(self.p, self.warmup_s), tapers=tapers, derived=DERIVED)

    def notify_reconnect(self) -> None:
        """串口重连后调用：热身重新开始，数据流频率统计清空。"""
        self._times.clear()
        self.t_start = time.time()
        self.reflex.arm(self.t_start)

    # ---------- 每帧喂给反射层的观测 ----------
    def _sensors(self, s: Sample, now: float) -> dict[str, float]:
        """把一帧转成 fly-reflex 认识的扁平字典。带状态的量在这里算好再塞进去。"""
        d = {
            "ax": s.ax, "ay": s.ay, "az": s.az,
            "gx": s.gx, "gy": s.gy, "gz": s.gz,
            "pitch": s.pitch, "roll": s.roll,
            "ldps": s.ldps, "rdps": s.rdps,
            "session_s": now - (self.t_start or now),
        }
        if self.neutral_l is not None:
            d["l_dev"] = abs(s.ldeg - self.neutral_l)
            d["r_dev"] = abs(s.rdeg - self.neutral_r)
        if self.backend == "spiking":        # 脉冲后端只认一个合并的关节信号
            wl = 0.0 if abs(s.ldps) > DPS_IGNORE_ABOVE else s.ldps
            wr = 0.0 if abs(s.rdps) > DPS_IGNORE_ABOVE else s.rdps
            d["joint_dps"] = max(abs(wl), abs(wr))
        return d

    # ---------- 急停判定 ----------
    def trip(self, s: Sample) -> Optional[str]:
        now = s.host_t
        if self.t_start is None:
            self.t_start = now
            self.reflex.arm(now)
        self._times.append(now)
        # 热身阶段只采中立位，不判定动态阈值（刚 ENABLE 时可能有瞬态）
        if now - self.t_start < self.warmup_s:
            self._warm_l.append(s.ldeg); self._warm_r.append(s.rdeg)
            return None
        if self.neutral_l is None:
            self._warm_l.sort(); self._warm_r.sort()
            self.neutral_l = self._warm_l[len(self._warm_l)//2] if self._warm_l else s.ldeg
            self.neutral_r = self._warm_r[len(self._warm_r)//2] if self._warm_r else s.rdeg
        v = self.reflex.update(now, self._sensors(s, now))
        # 数据流频率不再在这里判定：通信丢失由 bridge 的 supervisor 处理（清零 + 自动重连），不是急停
        self.reason = v.reason if v.action is not Action.OK else None
        return self.reason

    # ---------- assist 渐弱 ----------
    def assist_scale(self, s: Sample, tau_l: float, tau_r: float) -> float:
        """返回 0..1。tau_* 是本帧准备下发的力矩，用来累计正功预算。"""
        if self.neutral_l is None:
            return 0.0                                      # 热身期间不助力
        now = s.host_t
        sc = self.reflex.scale(now, self._sensors(s, now))   # 速度 / 角度渐弱由 fly-reflex 管
        # 正功预算（只累计设备对腿做的正功）——需要 1 秒滑动窗，按契约留在调用方
        wl = 0.0 if abs(s.ldps) > DPS_IGNORE_ABOVE else s.ldps
        wr = 0.0 if abs(s.rdps) > DPS_IGNORE_ABOVE else s.rdps
        if self._last_t is not None:
            dt = now - self._last_t
            pw = tau_l * math.radians(wl) + tau_r * math.radians(wr)
            if pw > 0: self._energy.append((now, pw * dt))
        self._last_t = now
        while self._energy and now - self._energy[0][0] > 1.0:
            self._energy.popleft()
        spent = sum(j for _, j in self._energy)
        if spent > self.p.assist_energy_J_per_s:
            self._budget_blown_until = now + 0.5
        detail = self.reflex.scale_detail(now, self._sensors(s, now))
        # 能量预算是个 1 秒滑动窗，不在 fly-reflex 里（它的 derived 必须无状态），
        # 所以单独算一条，和别的渐弱条并列展示。
        detail["energy"] = 0.0 if now < self._budget_blown_until else 1.0
        if now < self._budget_blown_until:
            sc = 0.0
        self.last_detail = {k: round(v, 3) for k, v in detail.items()}
        self.last_binding = min(detail, key=lambda k: detail[k]) if detail else ""
        self.energy_J_per_s = round(spent, 3)
        self.last_scale = sc
        return sc

    #: 渐弱条 id -> 人能读懂的名字，仪表盘直接用这张表。
    TAPER_LABELS = {"dps_l": "左腿转太快", "dps_r": "右腿转太快",
                    "angle_l": "左腿离中立位太远", "angle_r": "右腿离中立位太远",
                    "energy": "每秒做功超预算"}

    def scale_detail(self) -> dict:
        """最近一帧每条渐弱条的系数，以及是哪条在压着输出。给界面解释用。"""
        return {
            "scale": round(self.last_scale, 3),
            "detail": dict(self.last_detail),
            "binding": self.last_binding,
            "binding_label": self.TAPER_LABELS.get(self.last_binding, self.last_binding),
            "energy_J_per_s": getattr(self, "energy_J_per_s", 0.0),
            "energy_budget": self.p.assist_energy_J_per_s,
            "labels": self.TAPER_LABELS,
        }

    def stats(self) -> dict:
        """反射层的累计统计：跑了多少帧、每条规则触发几次、丢了多少饱和帧。"""
        return self.reflex.stats()
