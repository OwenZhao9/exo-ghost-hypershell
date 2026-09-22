"""把 `SafetyProfile` 翻译成 fly-reflex 的规则（停不停）和渐弱条（给多少）。

这一层是**纯的**：只做数据到数据的翻译，不碰时间、不碰状态、不做 IO。
所有带状态的东西（中立位、能量预算窗口）都留在 `control/safety.py` 里，
因为 fly-reflex 的契约要求 `derived=` 的函数必须是无状态纯函数。

命名对照（改这里的 id 会改急停原因文字，但不会改触发时机）：

    acc / gyro / tilt_pitch / tilt_roll / joint_l / joint_r / session   —— 停机规则
    dps_l / dps_r / angle_l / angle_r                 —— assist 渐弱条
"""
from __future__ import annotations

from collections.abc import Mapping

from fly_reflex import Action, Rule, TaperRule

from .profiles import SafetyProfile

__all__ = ["DPS_IGNORE_ABOVE", "TRIP_SIGNALS", "build_rules", "build_tapers", "tilt_deg"]

#: 关节角速度饱和值是 ±3276.7 °/s，超过这个数的帧一律当噪声丢掉（既不判定也不打断不了连续计数）。
DPS_IGNORE_ABOVE = 3000.0

#: 规则 id -> 稳定的信号类别，回归基准用它跨实现比较（见 tests/test_safety_regression.py）。
TRIP_SIGNALS = {
    "acc": "acc", "gyro": "gyro", "tilt_pitch": "tilt", "tilt_roll": "tilt", "tilt": "tilt",
    "joint_l": "joint", "joint_r": "joint", "session": "session",
}


def tilt_deg(s: Mapping[str, float]) -> float:
    """倾角：pitch 和 roll 里更大的那个绝对值。无状态纯函数。

    规则后端把 pitch / roll 分成两条规则判（这样原因里能说清是哪个轴翻了）；
    这个合并量是给脉冲后端用的——它需要一个固定长度的信号向量。
    """
    p = s.get("pitch", 0.0)
    r = s.get("roll", 0.0)
    return max(p if p >= 0.0 else -p, r if r >= 0.0 else -r)


DERIVED = {"tilt_deg": tilt_deg}


def build_rules(p: SafetyProfile, warmup_s: float) -> tuple[Rule, ...]:
    """按 acc → gyro → pitch → roll → 左髋 → 右髋 → 会话时长的顺序建规则。

    顺序有意义：同一帧多条命中时 fly-reflex 取**最严重**的，同严重度取**排在前面**的，
    所以这个顺序就是原来 if-return 链的优先级。

    全部用 SOFT_STOP 而不是 HARD_STOP：锁存由调用方（ExoBridge.trip）负责，
    本层只回答"这一帧安不安全"。两处都锁存会让 `trip()` 变成有状态的，
    破坏 tests/test_safety_regression.py 里记录的分工。
    """
    rules: list[Rule] = [
        Rule(id="acc", signal="acc_mag", op=">", threshold=p.acc_trip_g,
             action=Action.SOFT_STOP, warmup_s=warmup_s,
             message="腰部加速度 {value:.1f} g > {threshold} g（撞击/摔倒）"),
        Rule(id="gyro", signal="gyro_mag", op=">", threshold=p.gyro_trip_dps,
             action=Action.SOFT_STOP, warmup_s=warmup_s,
             message="腰部角速度 {value:.0f} °/s > {threshold}（急转/摔倒）"),
    ]
    if p.tilt_trip_deg is not None:      # 桌面档不判倾角：设备侧躺放着也正常
        for rid, sig in (("tilt_pitch", "pitch"), ("tilt_roll", "roll")):
            rules.append(
                Rule(id=rid, signal=sig, op="abs>", threshold=p.tilt_trip_deg,
                     action=Action.SOFT_STOP, warmup_s=warmup_s,
                     message="倾角 " + sig + "={value:.0f}° > {threshold}°（跌倒）"))
    for rid, sig, name in (("joint_l", "ldps", "左"), ("joint_r", "rdps", "右")):
        rules.append(
            Rule(id=rid, signal=sig, op="abs>", threshold=p.joint_dps_trip,
                 action=Action.SOFT_STOP, warmup_s=warmup_s,
                 consecutive=3,                       # 连续 3 帧（≈17 ms）才算，单帧毛刺不触发
                 ignore_above=DPS_IGNORE_ABOVE,
                 message=name + "髋角速度 {value:.0f} °/s > {threshold}"))
    rules.append(
        Rule(id="session", signal="session_s", op=">", threshold=p.max_session_s,
             action=Action.SOFT_STOP, warmup_s=warmup_s,
             message="会话超过 {threshold:.0f} s 上限"))
    return tuple(rules)


def build_tapers(p: SafetyProfile) -> tuple[TaperRule, ...]:
    """assist 的渐弱条：转太快压、离中立位太远压。能量预算不在这里（它需要滑动窗口）。"""
    return (
        TaperRule(id="dps_l", signal="ldps", soft=p.assist_dps_soft, hard=p.assist_dps_hard,
                  ignore_above=DPS_IGNORE_ABOVE),
        TaperRule(id="dps_r", signal="rdps", soft=p.assist_dps_soft, hard=p.assist_dps_hard,
                  ignore_above=DPS_IGNORE_ABOVE),
        TaperRule(id="angle_l", signal="l_dev", soft=p.assist_angle_soft_deg, hard=p.assist_angle_hard_deg),
        TaperRule(id="angle_r", signal="r_dev", soft=p.assist_angle_soft_deg, hard=p.assist_angle_hard_deg),
    )
