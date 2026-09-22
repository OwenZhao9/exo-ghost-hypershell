"""三种控制策略。输入每帧 Sample，输出 (τ_L, τ_R) Nm。
约定（实测标定）：两腿各自 +τ → +ω，所以：
  resist : τ = −c·ω   粘性阻尼（刹车），天然稳定
  assist : τ = +c·ω   负阻尼（顺着推），会放大动作，必须限幅、死区、低通
增益 c 的单位：Nm / (rad/s)。走路时髋角速度峰值约 150–250 °/s ≈ 2.6–4.4 rad/s。
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from bridge.serial_io import Sample

DPS_SATURATION = 3000.0     # |dps| 超过即视为饱和尖峰（实测饱和值 3276.7）

# 项目规则：任何力矩变化都要柔和。每个策略声明自己允许的斜坡（Nm/s），服务切换策略时写入 bridge。
RAMP_BY_POLICY = {"zero": 3.0, "resist": 3.0, "assist": 2.0, "hold": 1.5, "torque": 1.0}

# 方向约定（2026-09-22 用户现场确认）：两腿"向上抬"= 左腿负力矩/负角度方向，右腿正力矩/正角度方向
UP_SIGN = {"L": -1.0, "R": +1.0}


class TorquePolicy:
    """恒定力矩（桌面用）：持续输出 (τL, τR)，带一个到期时间，到期自动归零，防止忘记关。"""
    name = "torque"
    gain = 0.0

    ramp_nm_per_s = RAMP_BY_POLICY["torque"]     # 1 Nm/s：1.5 Nm 要 1.5 s 才到，不会有突然的力

    def __init__(self, tau_l: float, tau_r: float, seconds: float, max_torque: float = 1.5):
        import time as _t
        m = abs(max_torque)
        self.tau_l = max(-m, min(m, float(tau_l))); self.tau_r = max(-m, min(m, float(tau_r)))
        self.until = _t.time() + float(seconds)
        self.max_torque = m

    def torque(self, s: Sample, scale: float = 1.0) -> tuple[float, float]:
        import time as _t
        if _t.time() > self.until:
            return 0.0, 0.0
        return self.tau_l, self.tau_r

    def status(self) -> str:
        import time as _t
        return f"τ=({self.tau_l:+.2f},{self.tau_r:+.2f}) 剩余 {max(0.0, self.until - _t.time()):.0f}s"


class LowPass:
    """一阶低通，fc 截止频率 Hz，按实际 dt 更新"""
    def __init__(self, fc: float):
        self.fc = fc; self.y = None; self.t = None
    def __call__(self, x: float, t: float) -> float:
        if self.y is None or self.t is None or t <= self.t:
            self.y, self.t = x, t; return x
        dt = t - self.t; self.t = t
        a = dt / (dt + 1.0 / (2 * math.pi * self.fc))
        self.y += a * (x - self.y)
        return self.y


@dataclass
class Policy:
    name: str = "zero"
    gain: float = 0.0            # Nm per rad/s
    max_torque: float = 1.5      # 本策略自己的上限（bridge 还有一层软限幅）
    ramp_nm_per_s: float = 3.0   # 该策略允许的力矩斜坡
    deadband_dps: float = 8.0    # |ω| 小于此值不出力，防静止抖动
    lp_fc: float = 10.0          # 角速度低通截止 Hz（6 Hz 在快速换向时滞后明显）
    _lpL: LowPass = field(default_factory=lambda: LowPass(10.0), repr=False)
    _lpR: LowPass = field(default_factory=lambda: LowPass(10.0), repr=False)
    _lastL: float = 0.0
    _lastR: float = 0.0

    def __post_init__(self):
        self._lpL = LowPass(self.lp_fc); self._lpR = LowPass(self.lp_fc)

    def _clean(self, dps: float, last: float) -> float:
        return last if abs(dps) > DPS_SATURATION else dps

    def torque(self, s: Sample, scale: float = 1.0) -> tuple[float, float]:
        """scale 只作用于 assist（负阻尼渐弱）；resist 永远全额，因为它只会让系统更稳。"""
        wl = self._clean(s.ldps, self._lastL); self._lastL = wl
        wr = self._clean(s.rdps, self._lastR); self._lastR = wr
        wl = self._lpL(wl, s.host_t); wr = self._lpR(wr, s.host_t)
        if self.name == "zero" or self.gain == 0.0:
            return 0.0, 0.0
        sign = -1.0 if self.name == "resist" else +1.0
        out = []
        for w in (wl, wr):
            if abs(w) < self.deadband_dps:
                out.append(0.0); continue
            tau = sign * self.gain * math.radians(w)
            if self.name == "assist":
                tau *= max(0.0, min(1.0, scale))
            out.append(max(-self.max_torque, min(self.max_torque, tau)))
        return out[0], out[1]


def make_policy(name: str, gain: float, max_torque: float) -> Policy:
    name = name.lower()
    if name not in ("zero", "resist", "assist"):
        raise ValueError("policy 必须是 zero / resist / assist")
    if name == "assist":
        # 助力是负阻尼：默认更保守
        gain = min(gain, 0.6); max_torque = min(max_torque, 1.2)
    return Policy(name=name, gain=gain, max_torque=max_torque, ramp_nm_per_s=RAMP_BY_POLICY[name])


class HoldPolicy:
    """位置保持（PD）：τ = Kp·(θ_target − θ) − Kd·ω，目标角以 slew °/s 平滑过渡；未设目标的腿输出 0。
    仅用于桌面：穿戴时与人体较劲不安全。单位：Kp Nm/°，Kd Nm/(°/s)。
    """
    name = "hold"
    gain = 0.0
    ramp_nm_per_s = RAMP_BY_POLICY["hold"]

    def __init__(self, kp: float = 0.08, kd: float = 0.006, ki: float = 0.04, max_torque: float = 1.5, slew_dps: float = 15.0,
                 i_limit: float = 0.9):
        # slew 默认 15 °/s：60° 的移动要 4 秒，穿戴时人能跟上、能反应
        self.kp, self.kd, self.ki, self.max_torque, self.slew, self.i_limit = kp, kd, ki, max_torque, slew_dps, i_limit
        self.target = {"L": None, "R": None}      # 最终目标 °
        self._ref = {"L": None, "R": None}         # 当前平滑参考 °
        self._i = {"L": 0.0, "R": 0.0}             # 积分项 Nm（抵消重力/摩擦的静差）
        self._t = None
        self._lpL = LowPass(15.0); self._lpR = LowPass(15.0)
        self._lastL = 0.0; self._lastR = 0.0

    def set_target(self, leg: str, deg):
        self.target[leg] = None if deg is None else float(deg)
        self._i[leg] = 0.0
        if deg is None:
            self._ref[leg] = None

    def torque(self, s: Sample, scale: float = 1.0) -> tuple[float, float]:
        dt = 0.0 if self._t is None else max(0.0, min(0.05, s.host_t - self._t))
        self._t = s.host_t
        wl = self._lastL if abs(s.ldps) > DPS_SATURATION else s.ldps; self._lastL = wl
        wr = self._lastR if abs(s.rdps) > DPS_SATURATION else s.rdps; self._lastR = wr
        wl = self._lpL(wl, s.host_t); wr = self._lpR(wr, s.host_t)
        out = []
        for leg, th, w in (("L", s.ldeg, wl), ("R", s.rdeg, wr)):
            tgt = self.target[leg]
            if tgt is None:
                out.append(0.0); continue
            ref = self._ref[leg]
            if ref is None:
                ref = th                                   # 从当前位置开始平滑过渡
            step = self.slew * dt
            ref += max(-step, min(step, tgt - ref))
            self._ref[leg] = ref
            err = ref - th
            # 积分：只在参考已到达最终目标、且误差 > 1° 时累积；限幅防饱和
            if abs(ref - tgt) < 0.5 and abs(err) > 1.0:
                self._i[leg] = max(-self.i_limit, min(self.i_limit, self._i[leg] + self.ki * err * dt))
            elif abs(err) <= 1.0:
                self._i[leg] *= 0.98                   # 到位后缓慢泄放，避免长期顶着
            tau = self.kp * err - self.kd * w + self._i[leg]
            out.append(max(-self.max_torque, min(self.max_torque, tau)))
        return out[0], out[1]

    def status(self) -> str:
        return " ".join(f"{k}:{'—' if v is None else f'{v:.0f}°'}(I={self._i[k]:+.2f})" for k, v in self.target.items())
