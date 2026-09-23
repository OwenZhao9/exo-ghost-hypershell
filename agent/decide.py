"""Ghost 的直觉层：看一段数据，决定现在该用什么策略、助力给多少。

用 [jev-decide](https://github.com/OwenZhao9/jev-decide) 做带类型的决策：
问一个"三选一"的问题，直接拿到选择 + 概率 + 置信度，而不是让模型写一段话再去解析。
没有 API key 时自动落到本地 `rules` 后端（`agent/policy_rules.py`），断网照常工作。

**核心是置信度门控：不确定就别动。** 设备是绑在人身上的，
"我觉得大概可能是在走路" 不足以构成改变出力的理由——这种时候保持原状才是对的。

分工：
  实时线程   只调 `feed(s)`，就是往环形窗口里 append 一帧，O(1)
  工作线程   每隔 `period_s` 调一次 `tick()`，在这里做特征提取和决策；
             主循环保持可处理松劲与急停
  自动驾驶   默认**关闭**：Ghost 只给建议，人来决定采不采纳。
             `--autopilot` 打开后才会真的改策略，且仍然走 runtime.commands
             那条路，所有既有的安全限制（穿戴档禁令、急停锁存）原样生效。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from jev_decide import Choice, Decider, Score

from bridge.protocol import Sample

from .features import FEATURE_LABELS, extract
from .policy_rules import GAIN_MAX, OPTIONS, blocked, explain, gain_rules, gait, policy_weights

__all__ = ["Decision", "GhostDecider"]

QUESTION = "现在该用什么策略？"
RUBRIC = "assist 的增益该给多少（Nm per °/s）"


@dataclass(frozen=True)
class Decision:
    t: float
    want: str                 # Ghost 想切到哪个策略
    applied: str              # 门控之后真正采用的（置信度不足时 = 原策略）
    confidence: float
    probs: dict[str, float]
    gain: float
    backend: str
    degraded: bool
    why: str                  # 一句人话依据
    held_by: str = ""         # "" 没拦 | "gate" 置信度不足 | "hold" 刚换过，防抖期内
    features: dict[str, Any] = field(default_factory=dict)
    autopilot: bool = False   # 这次是不是真的下发了

    @property
    def held(self) -> bool:
        """想切但没切成。原因看 held_by：置信度不足，还是防抖期内。"""
        return bool(self.held_by)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t, "want": self.want, "applied": self.applied,
            "confidence": round(self.confidence, 3),
            "probs": {k: round(v, 3) for k, v in self.probs.items()},
            "gain": round(self.gain, 3), "backend": self.backend,
            "degraded": self.degraded, "held": self.held, "held_by": self.held_by,
            "autopilot": self.autopilot,
            "why": self.why, "features": self.features, "labels": FEATURE_LABELS,
        }


class GhostDecider:
    def __init__(self, *, window_s: float = 3.0, stream_hz: float = 180.0,
                 period_s: float = 2.0, min_confidence: float = 0.55,
                 min_hold_s: float = 6.0, autopilot: bool = False,
                 backend: str = "auto", api_key: Optional[str] = None,
                 base_url: Optional[str] = None, model: Optional[str] = None,
                 timeout_s: float = 1.0,
                 on_decision: Optional[Callable[[Decision], None]] = None) -> None:
        self.window: deque[Sample] = deque(maxlen=int(window_s * stream_hz))
        self.period_s = period_s
        self.min_confidence = min_confidence
        self.min_hold_s = min_hold_s        # 两次换策略之间至少隔这么久，防抖
        self.autopilot = autopilot
        self.on_decision = on_decision
        self.decider = Decider(backend, api_key=api_key, base_url=base_url,
                               model=model, timeout_s=timeout_s)
        self.last: Optional[Decision] = None
        self.n_decisions = 0
        self.n_held = 0                     # 被置信度、防抖或本地安全规则拦下来几次
        self.n_applied = 0                  # 自动驾驶真正下发几次
        self._last_tick = 0.0
        self._last_switch = 0.0

    # ---------------- 实时线程唯一会碰的东西 ----------------
    def feed(self, s: Sample) -> None:
        """O(1)，不做任何计算。特征提取和决策都在主循环里。"""
        self.window.append(s)

    # ---------------- 主循环每隔 period_s 调一次 ----------------
    def due(self, now: float) -> bool:
        return now - self._last_tick >= self.period_s

    def tick(self, now: float, *, current_policy: str, armed: bool,
             tripped: Optional[str], legs_offline: bool) -> Optional[Decision]:
        """做一次决策。没到点就返回 None。本方法会阻塞，
        所以只能在工作线程里调，不准进串口读线程或命令主循环。"""
        if not self.due(now):
            return None
        self._last_tick = now

        # deque.copy() 在 C 层取得快照，避免串口线程 append 时迭代器报错。
        state = extract(list(self.window.copy()))
        state.update(armed=bool(armed), tripped=tripped or "",
                     legs_offline=bool(legs_offline), current=current_policy)

        if blocked(state):
            # 无效数据没有询问远端的必要，也不能让模型覆盖 zero。
            c = Choice(value="zero", probs={"zero": 1.0, "resist": 0.0, "assist": 0.0},
                       confidence=1.0, latency_ms=0.0, backend="rules")
            g = Score(value=0.0, lo=0.0, hi=GAIN_MAX, confidence=1.0,
                      latency_ms=0.0, backend="rules")
        else:
            c = self.decider.choice(state, QUESTION, OPTIONS, rules=policy_weights)
            g = self.decider.score(state, RUBRIC, 0.0, GAIN_MAX, rules=gain_rules)
        applied = Decider.gate(c, min_confidence=self.min_confidence,
                               on_low="keep", current=current_policy)
        held_by = "gate" if applied != c.value else ""
        # 防抖：刚换过策略就先稳一会儿，别让 Ghost 在两个策略之间来回横跳
        if (applied != current_policy and applied != "zero"
                and now - self._last_switch < self.min_hold_s):
            applied = current_policy
            held_by = "hold"

        # 模型的概率不是硬件安全依据。数据不足、急停和掉线必须越过
        # 置信度门控与防抖，直接建议 zero；助力还需本地步态证据。
        if blocked(state) or (applied == "assist" and gait(state) < 0.75):
            applied = "zero"
            held_by = "safety"
        gain = min(max(0.0, g.value), gain_rules(state)) if applied == "assist" else 0.0

        d = Decision(t=now, want=c.value, applied=applied, confidence=c.confidence,
                     probs=dict(c.probs), gain=gain, backend=c.backend,
                     degraded=c.degraded or g.degraded, why=explain(state),
                     features={k: v for k, v in state.items() if k in FEATURE_LABELS},
                     held_by=held_by,
                     autopilot=self.autopilot and applied != current_policy)
        self.n_decisions += 1
        if d.held:
            self.n_held += 1
        if d.autopilot:
            self.n_applied += 1
            self._last_switch = now
        self.last = d
        if self.on_decision:
            self.on_decision(d)
        return d

    def snapshot(self) -> dict[str, Any]:
        return {
            "autopilot": self.autopilot,
            "min_confidence": self.min_confidence,
            "decisions": self.n_decisions,
            "held": self.n_held,
            "applied": self.n_applied,
            "backend": self.decider.health().get("backend", "?"),
            "last": None if self.last is None else self.last.to_dict(),
        }
