"""直觉层：特征 → 权重 → 带置信度的决策 → 门控。

三条不能破的规矩：
  1. 特征提取是纯的，同一段窗口算两次结果一样；
  2. 置信度必须能区分"很确定"和"勉强"，否则门控是摆设；
  3. 不安全的状态（急停、掉线、未武装、数据不足）下只能给 zero。
"""
from __future__ import annotations

import math

import pytest
from jev_decide import Choice, Decider, Score

from agent.decide import GhostDecider
from agent.features import extract
from agent.policy_rules import OPTIONS, blocked, gain_rules, gait, jerk, policy_weights
from bridge.protocol import Sample
from bridge.wearer import GAITS, angles

HZ = 180.0
RAD2DEG = 180.0 / math.pi


def frames(gait_name: str | None, seconds: float = 3.0, still_deg: float = 0.0):
    """按穿戴者模型生成一段窗口；gait_name=None 表示站着不动。"""
    out = []
    for i in range(int(seconds * HZ)):
        t = i / HZ
        if gait_name is None:
            l = r = (still_deg, 0.0)
        else:
            a = angles(GAITS[gait_name], t)
            l, r = a["L"], a["R"]
        out.append(Sample(host_t=t, ms=t * 1000, pitch=0.0, roll=0.0, yaw=0.0,
                          gx=0.0, gy=0.0, gz=0.0, ax=0.0, ay=0.0, az=1.0, kpa=101.0,
                          ldeg=l[0] * RAD2DEG, rdeg=r[0] * RAD2DEG,
                          ldps=l[1] * RAD2DEG, rdps=r[1] * RAD2DEG))
    return out


def state_for(gait_name, **extra):
    st = extract(frames(gait_name))
    st.update(dict(armed=True, tripped="", legs_offline=False, current="zero"))
    st.update(extra)
    return st


# ---------------------------------------------------------------- 特征

def test_extract_is_pure():
    w = frames("walk")
    assert extract(w) == extract(w)


def test_too_few_frames_is_not_usable():
    got = extract(frames("walk", seconds=0.05))
    assert got["usable"] is False and "帧" in got["reason"]


def test_walking_looks_like_walking():
    st = extract(frames("walk"))
    assert 0.7 <= st["cadence_hz"] <= 1.3          # 预设是 1.0 Hz
    assert st["antiphase"] > 0.9                    # 左右腿严格反相
    assert st["rom_deg"] > 30
    assert st["still_frac"] < 0.2


def test_standing_still_looks_still():
    st = extract(frames(None))
    assert st["still_frac"] == 1.0
    assert st["cadence_hz"] == 0.0
    assert st["rom_deg"] == 0.0


def test_limping_breaks_the_antiphase_not_the_amplitude():
    """跛行的摆幅没小多少，区别全在两腿相位上——特征必须能分开这两件事。"""
    walk, limp = extract(frames("walk")), extract(frames("limp"))
    assert limp["rom_deg"] > 0.6 * walk["rom_deg"]
    assert limp["antiphase"] < 0.6 * walk["antiphase"]


# ---------------------------------------------------------------- 规则

@pytest.mark.parametrize("why,extra", [
    ("急停", {"tripped": "倾角超限"}),
    ("掉线", {"legs_offline": True}),
    ("未武装", {"armed": False}),
    ("数据率低", {"hz": 40.0}),
])
def test_unsafe_states_allow_only_zero(why, extra):
    w = policy_weights(state_for("walk", **extra))
    assert w == {"zero": 1.0}, f"{why} 时不该给 zero 以外的选项任何质量"
    assert gain_rules(state_for("walk", **extra)) == 0.0
    assert blocked(state_for("walk", **extra))


def test_gait_score_ranks_walk_above_limp_above_still():
    assert gait(state_for("walk")) > gait(state_for("limp")) > gait(state_for(None))


def test_jerk_and_gait_are_mutually_exclusive():
    """一段数据不可能既是规律步态又是失控甩动。"""
    for name in (None, "slow", "walk", "fast", "limp"):
        st = state_for(name)
        assert gait(st) * jerk(st) < 0.3


# ---------------------------------------------------------------- 决策与门控

def decide(gait_name, **extra):
    d = Decider(backend="rules")
    st = state_for(gait_name, **extra)
    return d.choice(st, "策略？", OPTIONS, rules=policy_weights)


def test_clear_gait_is_confident_enough_to_act():
    c = decide("walk")
    assert c.value == "assist"
    assert c.confidence >= 0.55, "清楚的步态必须过得了默认门槛，否则助力永远用不上"


def test_ambiguous_gait_is_not_confident_enough():
    c = decide("limp")
    assert c.confidence < 0.55
    assert Decider.gate(c, min_confidence=0.55, on_low="keep", current="zero") == "zero"


def test_standing_still_picks_zero():
    c = decide(None)
    assert c.value == "zero" and c.confidence >= 0.55


def test_probs_always_sum_to_one():
    for name in (None, "slow", "walk", "fast", "limp"):
        c = decide(name)
        assert sum(c.probs.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------- GhostDecider

def fresh(**kw) -> GhostDecider:
    kw.setdefault("period_s", 0.0)
    return GhostDecider(**kw)


def test_feed_then_tick_produces_a_decision():
    g = fresh()
    for s in frames("walk"):
        g.feed(s)
    d = g.tick(100.0, current_policy="zero", armed=True, tripped=None, legs_offline=False)
    assert d.want == "assist" and d.applied == "assist" and d.held is False
    assert 0.0 < d.gain <= 0.30


def test_low_confidence_keeps_the_current_policy_and_says_why():
    g = fresh()
    for s in frames("limp"):
        g.feed(s)
    d = g.tick(100.0, current_policy="resist", armed=True, tripped=None, legs_offline=False)
    assert d.applied == "resist" and d.held_by == "gate"


def test_zero_preempts_anti_flap_hold():
    """回到 zero 不受防抖期阻拦。"""
    g = fresh(min_hold_s=60.0, autopilot=True)
    for s in frames("walk"):
        g.feed(s)
    first = g.tick(100.0, current_policy="zero", armed=True, tripped=None, legs_offline=False)
    assert first.autopilot is True
    g.window.clear()
    for s in frames(None):
        g.feed(s)
    second = g.tick(101.0, current_policy="assist", armed=True, tripped=None, legs_offline=False)
    assert second.want == "zero" and second.applied == "zero"
    assert second.held_by == ""


def test_evomap_model_advice_is_bounded_by_local_gait_evidence(monkeypatch):
    g = fresh(backend="llm", api_key="sk-evomap-test",
              base_url="https://api.evomap.ai/v1",
              model="evomap-gemini-3.1-pro-preview")
    assert g.decider._backends["llm"].endpoint == "https://api.evomap.ai/v1/chat/completions"
    assert g.decider._backends["llm"].model == "evomap-gemini-3.1-pro-preview"
    monkeypatch.setattr(g.decider, "choice", lambda *a, **kw: Choice(
        value="assist", probs={"zero": 0.01, "resist": 0.01, "assist": 0.98},
        confidence=0.95, latency_ms=1, backend="llm"))
    monkeypatch.setattr(g.decider, "score", lambda *a, **kw: Score(
        value=0.30, lo=0, hi=0.30, confidence=0.95, latency_ms=1, backend="llm"))
    for s in frames("walk"):
        g.feed(s)
    walking = g.tick(100.0, current_policy="zero", armed=True,
                     tripped=None, legs_offline=False)
    assert walking.applied == "assist"
    assert 0 < walking.gain <= gain_rules(state_for("walk"))
    assert walking.autopilot is False

    g.window.clear()
    for s in frames(None):
        g.feed(s)
    standing = g.tick(101.0, current_policy="assist", armed=True,
                      tripped=None, legs_offline=False)
    assert standing.want == "assist"
    assert standing.applied == "zero" and standing.gain == 0
    assert standing.held_by == "safety"

    offline = g.tick(102.0, current_policy="assist", armed=True,
                     tripped=None, legs_offline=True)
    assert offline.applied == "zero" and offline.gain == 0


def test_evomap_gateway_request_uses_bound_model_and_aggregate_state(monkeypatch):
    import json
    from jev_decide._backends import llm

    sent = []

    def fake_post(url, payload, *, headers, timeout_s):
        sent.append((url, payload, headers))
        state = json.loads(payload["messages"][1]["content"])["state"]
        assert "cadence_hz" in state and "antiphase" in state
        assert "ldeg" not in state and "serial" not in state
        schema = payload["response_format"]["json_schema"]["name"]
        if schema == "jev_decide_choice":
            answer = {"choice": "assist",
                      "probabilities": {"zero": 0.01, "resist": 0.01, "assist": 0.98}}
        else:
            answer = {"probabilities": {"0": 0.01, "1": 0.01, "2": 0.01,
                                         "3": 0.01, "4": 0.96}}
        return {"choices": [{"message": {"content": json.dumps(answer)}}]}

    monkeypatch.setattr(llm, "post_json", fake_post)
    g = fresh(backend="llm", api_key="sk-evomap-test",
              base_url="https://api.evomap.ai/v1",
              model="evomap-gemini-3.1-pro-preview")
    for s in frames("walk"):
        g.feed(s)
    d = g.tick(100.0, current_policy="zero", armed=True,
               tripped=None, legs_offline=False)
    assert d.backend == "llm" and d.applied == "assist" and not d.autopilot
    assert len(sent) == 2
    assert all(url == "https://api.evomap.ai/v1/chat/completions" for url, _, _ in sent)
    assert all(payload["model"] == "evomap-gemini-3.1-pro-preview" for _, payload, _ in sent)
    assert all(headers["Authorization"] == "Bearer sk-evomap-test" for _, _, headers in sent)


def test_evomap_is_not_called_when_sensor_state_is_blocked(monkeypatch):
    g = fresh(backend="llm", api_key="sk-evomap-test",
              base_url="https://api.evomap.ai/v1",
              model="evomap-gemini-3.1-pro-preview")
    def unexpected(*args, **kwargs):
        raise AssertionError("blocked state must not call the model")
    monkeypatch.setattr(g.decider, "choice", unexpected)
    monkeypatch.setattr(g.decider, "score", unexpected)
    for s in frames("walk"):
        g.feed(s)
    d = g.tick(100.0, current_policy="assist", armed=True,
               tripped="operator estop", legs_offline=False)
    assert d.applied == "zero" and d.gain == 0 and d.held_by == "safety"


def test_tick_respects_its_period():
    g = GhostDecider(period_s=10.0)
    for s in frames("walk"):
        g.feed(s)
    assert g.tick(100.0, current_policy="zero", armed=True, tripped=None, legs_offline=False)
    assert g.tick(100.5, current_policy="zero", armed=True, tripped=None, legs_offline=False) is None


def test_feed_is_cheap_enough_for_the_control_loop():
    """实时线程只会调 feed，180 Hz 下它必须几乎不花时间。"""
    import time as _t
    g = fresh()
    w = frames("walk")
    t0 = _t.perf_counter()
    for _ in range(10):
        for s in w:
            g.feed(s)
    per_call_us = (_t.perf_counter() - t0) / (10 * len(w)) * 1e6
    assert per_call_us < 5.0, f"feed 每次 {per_call_us:.1f} µs，对 180 Hz 太慢"


def test_snapshot_is_json_safe():
    import json
    g = fresh()
    for s in frames("walk"):
        g.feed(s)
    g.tick(100.0, current_policy="zero", armed=True, tripped=None, legs_offline=False)
    json.dumps(g.snapshot())


def test_wearer_trajectory_is_deterministic_and_bounded():
    for name, spec in GAITS.items():
        a = angles(spec, 0.37)
        assert a == angles(spec, 0.37)
        for leg, (pos, _vel) in a.items():
            assert abs(pos) <= spec.amp_deg * math.pi / 180 + 1e-9, f"{name}/{leg} 超出摆幅"
