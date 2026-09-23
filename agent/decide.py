"""Ghost 的直觉层：看一段数据，决定现在该用什么策略、助力给多少。

用 [jev-decide](https://github.com/OwenZhao9/jev-decide) 做带类型的决策：
问一个"三选一"的问题，直接拿到选择 + 概率 + 置信度，而不是让模型写一段话再去解析。
没有 API key 时自动落到本地 `rules` 后端（`agent/policy_rules.py`），断网照常工作。

**核心是置信度门控：不确定就别动。** 设备是绑在人身上的，
"我觉得大概可能是在走路" 不足以构成改变出力的理由——这种时候保持原状才是对的。

分工：
  实时线程   只调 `feed(s)`，就是往环形窗口里 append 一帧，O(1)
  主循环     每隔 `period_s` 调一次 `tick()`，在这里做特征提取和决策
  自动驾驶   默认**关闭**：Ghost 只给建议，人来决定采不采纳。
             `--autopilot` 打开后才会真的改策略，且仍然走 runtime.commands
             那条路，所有既有的安全限制（穿戴档禁令、急停锁存）原样生效。
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from jev_decide import Choice, Decider

from bridge.protocol import Sample

from .features import FEATURE_LABELS, extract
from .policy_rules import OPTIONS, blocked, explain, gain_rules, policy_weights

__all__ = ["Decision", "GhostDecider"]

QUESTION = "现在该用什么策略？"


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
                 timeout_s: float = 1.0,
                 background: bool = False,
                 on_decision: Optional[Callable[[Decision], None]] = None) -> None:
        self.window: deque[Sample] = deque(maxlen=int(window_s * stream_hz))
        self.period_s = period_s
        self.min_confidence = min_confidence
        self.min_hold_s = min_hold_s        # 两次换策略之间至少隔这么久，防抖
        self.autopilot = autopilot
        self.on_decision = on_decision
        self.decider = Decider(backend, api_key=api_key, timeout_s=timeout_s)
        self.safety_decider = Decider("rules")
        self.backend_mode = backend
        self.background = background
        self._worker: Optional[ThreadPoolExecutor] = None
        self._pending: Optional[Future[Choice]] = None
        self._pending_state: Optional[dict[str, Any]] = None
        self._pending_at = 0.0
        self._pending_policy = ""
        self._last_unsafe_tick = 0.0
        self._last_unsafe_key: tuple[str, str] = ("", "")
        self.last: Optional[Decision] = None
        self.n_decisions = 0
        self.n_held = 0                     # 被置信度门控拦下来几次
        self.n_applied = 0                  # 自动驾驶真正下发几次
        self._last_tick = 0.0
        self._last_switch = 0.0

    # ---------------- 实时线程唯一会碰的东西 ----------------
    def feed(self, s: Sample) -> None:
        """O(1)，不做任何计算。特征提取和决策都在主循环里。"""
        self.window.append(s)

    # ---------------- 主循环每隔 period_s 调一次 ----------------
    def due(self, now: float) -> bool:
        return self._pending is not None or now - self._last_tick >= self.period_s

    def close(self) -> None:
        if self._worker is not None:
            self._worker.shutdown(wait=False, cancel_futures=True)

    def tick(self, now: float, *, current_policy: str, armed: bool,
             tripped: Optional[str], legs_offline: bool,
             sample_age_s: Optional[float] = None,
             reconnecting: bool = False) -> Optional[Decision]:
        """安全状态立即归零；后台模式只收取已完成的网络结果，不阻塞主循环。"""
        state = extract(list(self.window))
        state.update(armed=bool(armed), tripped=tripped or "",
                     legs_offline=bool(legs_offline), current=current_policy)
        if reconnecting or (sample_age_s is None and self.background):
            state.update(usable=False, reason="设备未提供新帧")
        elif sample_age_s is not None and sample_age_s > 0.5:
            state.update(usable=False, reason="设备数据已过期")
        unsafe = blocked(state)
        if unsafe:
            # Never wait for, or trust, a remote answer in an unsafe state.
            if self._pending is not None:
                self._pending.cancel()
                self._pending_state = None
            key = (unsafe, current_policy)
            if key == self._last_unsafe_key and now - self._last_unsafe_tick < self.period_s:
                return None
            self._last_unsafe_key = key
            self._last_unsafe_tick = now
            self._last_tick = now
            c = self.safety_decider.choice(state, QUESTION, OPTIONS, rules=policy_weights)
            return self._finish(now, state, c, current_policy, unsafe=True)

        if not self.due(now):
            return None

        if self.background:
            if self._pending is not None:
                if not self._pending.done():
                    return None
                future, request_state = self._pending, self._pending_state
                request_at, request_policy = self._pending_at, self._pending_policy
                self._pending = None
                self._pending_state = None
                # A stale answer cannot command a different physical state.
                if (request_state is None or request_policy != current_policy
                        or now - request_at > max(self.period_s, 0.5)):
                    return None
                c = future.result()
                return self._finish(now, state, c, current_policy)
            self._last_tick = now
            if self._worker is None:
                self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jev-choice")
            self._pending_state = state
            self._pending_at = now
            self._pending_policy = current_policy
            self._pending = self._worker.submit(
                self.decider.choice, state, QUESTION, OPTIONS, rules=policy_weights)
            return None

        self._last_tick = now
        c = self.decider.choice(state, QUESTION, OPTIONS, rules=policy_weights)
        return self._finish(now, state, c, current_policy)

    def _finish(self, now: float, state: dict[str, Any], c: Choice,
                current_policy: str, *, unsafe: bool = False) -> Decision:
        # Physical gain is deterministic; Jev only selects among named policies.
        gain = gain_rules(state)
        applied = Decider.gate(c, min_confidence=self.min_confidence,
                               on_low="keep", current=current_policy)
        held_by = "gate" if applied != c.value else ""
        # 防抖：刚换过策略就先稳一会儿，别让 Ghost 在两个策略之间来回横跳
        if not unsafe and applied != current_policy and now - self._last_switch < self.min_hold_s:
            applied = current_policy
            held_by = "hold"

        d = Decision(t=now, want=c.value, applied=applied, confidence=c.confidence,
                     probs=dict(c.probs), gain=gain, backend=c.backend,
                     degraded=c.degraded, why=explain(state),
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
            "backend": self.backend_mode,
            "pending": self._pending is not None,
            "last": None if self.last is None else self.last.to_dict(),
        }
