"""Last local gate between an agent decision and an actuator policy command."""
from __future__ import annotations

from typing import Any, Mapping

from .policy_rules import blocked, gait


def next_command(decision: Any, *, current_policy: str, current_gain: float,
                 fresh: Mapping[str, Any], sample_recent: bool, quiet: bool,
                 min_confidence: float) -> dict[str, Any] | None:
    """Return a bounded command, or zero when current evidence is unsafe.

    Cloud decisions are only mode hints. The latest sensor window and the local
    hardware state must still pass before the service may change any output.
    """
    unsafe = blocked(fresh) or not sample_recent or quiet
    if decision.applied == "assist" and gait(fresh) < 0.75:
        unsafe = True
    if unsafe or decision.applied not in {"zero", "resist", "assist"}:
        return {"op": "zero"} if current_policy != "zero" else None
    if decision.applied != current_policy:
        return {"op": "policy", "policy": decision.applied,
                "gain": min(decision.gain, 0.1) if decision.applied == "assist" else 0.3,
                "max": 0.5}
    if decision.applied == "assist":
        want = (min(decision.gain, 0.1) if decision.confidence >= min_confidence
                else min(decision.gain, current_gain))
        if abs(want - current_gain) >= 0.05:
            return {"op": "policy", "policy": "assist", "gain": want, "max": 0.5}
    return None
