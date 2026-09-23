"""Second-stage, typed jEV review of a completed visual observation.

jEV sees only the validated EvoMap result, not the photograph. A missing or
failed TypeSafe backend must never turn a picture into a motor cue.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from jev_decide import Decider

OPTIONS = ("unknown", "left", "right")
MIN_VISION_CONFIDENCE = 0.85
MIN_JEV_CONFIDENCE = 0.75
MIN_JEV_PROBABILITY = 0.80
QUESTION = (
    "仅根据已完成的静态照片识别报告，判断画面哪一侧看起来更空。"
    "只在报告的方向、置信度、可见物体和描述相互支持时选择同一方向；"
    "证据不足、模糊、遮挡、矛盾或可能涉及道路安全时选择 unknown。"
    "这是受看护的支架演示，不是行走或导盲指令。"
)


def decide_visual_cue(vision: Mapping[str, Any], *, decider: Decider | None = None) -> dict[str, Any]:
    """Accept a direction only after an actual, agreeing jEV decision.

    The library always has a local rules fallback. We still call it so its
    health/latency is visible, but reject fallback answers for this motor path.
    """
    direction = vision.get("direction")
    confidence = vision.get("confidence")
    result: dict[str, Any] = {
        "direction": "unknown", "jev_choice": "unknown",
        "jev_confidence": 0.0, "jev_backend": "none",
        "jev_status": "vision_uncertain", "jev_seconds": None,
    }
    if (direction not in {"left", "right"} or
            isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or
            not math.isfinite(confidence) or confidence < MIN_VISION_CONFIDENCE):
        return result

    state = {
        "visual_direction": direction,
        "visual_confidence": round(float(confidence), 3),
        "description": str(vision.get("description", ""))[:240],
        "objects": [item["label"] for item in vision.get("annotations", [])[:3]
                    if isinstance(item, dict) and isinstance(item.get("label"), str)],
        "context": "supervised tabletop demo; no walking guidance",
    }
    decider = decider or Decider("jev", timeout_s=2.0,
                                fallback_chain=("jev", "rules"))
    choice = decider.choice(state, QUESTION, OPTIONS, rules=lambda _: "unknown")
    result.update(jev_choice=choice.value, jev_confidence=round(choice.confidence, 3),
                  jev_backend=choice.backend, jev_seconds=round(choice.latency_ms / 1000, 2))
    if choice.backend != "jev" or choice.degraded:
        result["jev_status"] = "unavailable"
    elif (choice.confidence < MIN_JEV_CONFIDENCE or
          choice.probs.get(choice.value, 0) < MIN_JEV_PROBABILITY):
        result["jev_status"] = "low_confidence"
    elif choice.value != direction:
        result["jev_status"] = "disagreed"
    else:
        result["jev_status"] = "accepted"
        result["direction"] = direction
    return result
