"""本地决策规则：由特征算出每个策略的权重。

**纯函数**，所以整条决策链断网也能跑，而且可以逐条解释给人听。

为什么返回的是权重而不是直接选一个：一个只会给 one-hot 答案的本地函数，
置信度永远是 1.0，`Decider.gate()` 就成了摆设——而没有 API key 时 `rules`
正是唯一可用的后端。给出权重，"这次很接近"才能如实反映成低置信度，
门控才拦得住。（jev-decide v0.1.1 为此加了字典返回值的支持。）
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["GAIN_MAX", "OPTIONS", "explain", "gain_rules", "policy_weights"]

OPTIONS = ("zero", "resist", "assist")
GAIN_MAX = 0.30          # assist 增益上限，穿戴时的保守值（项目规则：力要慢要小）

# 步态的合理区间：步频 0.5~1.8 Hz（慢走到快走），两腿要反相，摆幅要够大
CADENCE_BAND = (0.35, 0.55, 1.8, 2.4)
ANTIPHASE_RAMP = (0.15, 0.55)
ROM_RAMP = (8.0, 25.0)
JERK_RAMP = (180.0, 400.0)      # 峰值角速度：超过 400 °/s 就是甩动而不是走路


def _ramp(x: float, lo: float, hi: float) -> float:
    """lo 以下 0，hi 以上 1，中间线性。"""
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    return (x - lo) / (hi - lo)


def _band(x: float, lo0: float, lo1: float, hi1: float, hi0: float) -> float:
    """梯形隶属度：[lo1, hi1] 内为 1，lo0 以下 / hi0 以上为 0。"""
    if x <= lo0 or x >= hi0:
        return 0.0
    if x < lo1:
        return (x - lo0) / (lo1 - lo0)
    if x > hi1:
        return (hi0 - x) / (hi0 - hi1)
    return 1.0


def gait(state: Mapping[str, Any]) -> float:
    """0..1：这段数据有多像在规律地走路。三个条件是与的关系，一个不满足就归零。"""
    return (_band(float(state.get("cadence_hz", 0.0)), *CADENCE_BAND)
            * _ramp(float(state.get("antiphase", 0.0)), *ANTIPHASE_RAMP)
            * _ramp(float(state.get("rom_deg", 0.0)), *ROM_RAMP))


def jerk(state: Mapping[str, Any]) -> float:
    """0..1：有多像不受控的快速甩动（这种情况阻尼比助力有用）。"""
    return _ramp(float(state.get("peak_dps", 0.0)), *JERK_RAMP) * (1.0 - gait(state))


def blocked(state: Mapping[str, Any]) -> str:
    """有没有"根本不用讨论"的理由。返回理由字符串，没有就返回空串。"""
    if not state.get("usable"):
        return str(state.get("reason", "数据不足"))
    if state.get("tripped"):
        return "处于急停锁存"
    if state.get("legs_offline"):
        return "腿板掉线"
    if not state.get("armed"):
        return "未武装"
    if float(state.get("hz", 0.0)) < 120.0:
        return f"数据率只有 {state.get('hz')} Hz，速度估计不可信"
    return ""


def policy_weights(state: Mapping[str, Any]) -> dict[str, float]:
    """{策略: 权重}。权重由 jev-decide 归一化成概率，形状决定置信度。"""
    if blocked(state):
        return {"zero": 1.0}                 # 不安全时不给别的选项任何质量
    g = gait(state)
    j = jerk(state)
    idle = float(state.get("still_frac", 0.0))
    return {
        # zero 的分量 = 静着不动 + "别的解释都不成立"。所以拿不准时质量自动回到 zero，
        # 而步态非常清楚时它会让开——不是靠一个拍脑袋的固定底票压着。
        "zero": 0.10 + 2.0 * idle + 1.2 * (1.0 - max(g, j)),
        "resist": 0.05 + 2.5 * j,
        "assist": 0.05 + 2.5 * g,
    }


def gain_rules(state: Mapping[str, Any]) -> float:
    """assist 增益：步态越清楚给得越多，但永远不超过 GAIN_MAX。"""
    if blocked(state):
        return 0.0
    return round(GAIN_MAX * gait(state), 3)


def explain(state: Mapping[str, Any]) -> str:
    """一句人能读懂的依据，写进日志和仪表盘。"""
    why = blocked(state)
    if why:
        return f"{why} → 只能 zero"
    return (f"步态相似度 {gait(state):.2f}（步频 {state.get('cadence_hz')} Hz、"
            f"反相 {state.get('antiphase')}、摆幅 {state.get('rom_deg')}°）、"
            f"甩动 {jerk(state):.2f}（峰值 {state.get('peak_dps')} °/s）、"
            f"静止占比 {state.get('still_frac')}")
