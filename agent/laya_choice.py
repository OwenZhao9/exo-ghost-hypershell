"""Optional local Laya policy chooser for isolated simulation experiments."""
from __future__ import annotations

import math
import time
from typing import Any

from jev_decide import Choice, Decider

from .policy_rules import OPTIONS, policy_weights

MODEL = "aac6fef/laya-multilingual-mlx"
REVISION = "f2b4faf51023039425946074e2cf1361d2db11d5"
QUESTIONS = {"policy": {
    "type": "choice",
    "instructions": "根据最近三秒的外骨骼运动特征，选择适合的策略；证据不足时选 zero。",
    "criteria": {
        "zero": "静止、数据模糊或步行证据不足时松劲",
        "resist": "快速、不规则甩动且不像正常步行时增加阻尼",
        "assist": "规律、双腿反相、摆幅充足的步行时辅助",
    },
}}


class LayaChoice:
    """Load the local checkpoint only on the decision worker, never on the stream thread."""

    def __init__(self) -> None:
        self._agent: Any = None
        self._rules = Decider("rules")

    def choice(self, state: dict[str, Any], *_args: Any, **_kwargs: Any) -> Choice:
        started = time.perf_counter()
        try:
            if self._agent is None:
                import laya_mlx as laya
                from huggingface_hub import snapshot_download
                # Never let a large first-time download occupy the decision worker.
                # The checkpoint is prepared separately and verified in the cache.
                checkpoint = snapshot_download(MODEL, revision=REVISION,
                                               local_files_only=True)
                self._agent = laya.load(checkpoint)
            features = {k: state[k] for k in (
                "hz", "still_frac", "cadence_hz", "antiphase", "rom_deg",
                "mean_dps", "peak_dps", "tilt_deg") if k in state}
            answer = self._agent.predict(features, QUESTIONS)["answers"]["policy"]
            value = answer["choice"]
            probs = answer["probabilities"]
            confidence = float(answer["confidence"])
            if (value not in OPTIONS or set(probs) != set(OPTIONS)
                    or not all(math.isfinite(float(p)) and 0 <= float(p) <= 1
                               for p in probs.values())
                    or not math.isclose(sum(float(p) for p in probs.values()), 1.0,
                                        abs_tol=0.002)
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("invalid Laya choice")
            return Choice(value=value, probs={k: float(v) for k, v in probs.items()},
                          confidence=confidence,
                          latency_ms=(time.perf_counter() - started) * 1000,
                          backend="laya")
        except Exception as exc:
            fallback = self._rules.choice(state, "现在该用什么策略？", OPTIONS,
                                          rules=policy_weights)
            return Choice(value=fallback.value, probs=fallback.probs,
                          confidence=fallback.confidence,
                          latency_ms=(time.perf_counter() - started) * 1000,
                          backend="rules", degraded=True,
                          note=f"Laya unavailable: {type(exc).__name__}")
