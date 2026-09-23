"""直觉层：特征 → 权重 → 带置信度的决策 → 门控。

三条不能破的规矩：
  1. 特征提取是纯的，同一段窗口算两次结果一样；
  2. 置信度必须能区分"很确定"和"勉强"，否则门控是摆设；
  3. 不安全的状态（急停、掉线、未武装、数据不足）下只能给 zero。
"""
from __future__ import annotations

import math

import pytest
from jev_decide import Decider

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


def test_anti_flap_hold_is_reported_separately_from_the_gate():
    """刚换过策略就想再换，要说清是防抖拦的，不是置信度不够。"""
    g = fresh(min_hold_s=60.0, autopilot=True)
    for s in frames("walk"):
        g.feed(s)
    first = g.tick(100.0, current_policy="zero", armed=True, tripped=None, legs_offline=False)
    assert first.autopilot is True
    g.window.clear()
    for s in frames(None):
        g.feed(s)
    second = g.tick(101.0, current_policy="assist", armed=True, tripped=None, legs_offline=False)
    assert second.want == "zero" and second.applied == "assist"
    assert second.held_by == "hold"                 # 防抖，不是门控


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


def test_remote_choice_cannot_set_physical_gain(monkeypatch):
    """Even a confident remote assist choice cannot create gain during stillness."""
    g = fresh(backend="rules")
    for s in frames(None):
        g.feed(s)
    confident_assist = Decider("rules").choice(
        state_for("walk"), "策略？", OPTIONS, rules=policy_weights)
    monkeypatch.setattr(g.decider, "choice", lambda *a, **kw: confident_assist)
    d = g.tick(100.0, current_policy="zero", armed=True,
               tripped=None, legs_offline=False)
    assert d.want == "assist"
    assert d.gain == 0.0


def test_existing_jev_decide_library_sends_typesafe_choice(monkeypatch):
    """The exoskeleton uses the pinned library's real HTTP adapter, mocked at I/O."""
    import jev_decide._backends.jev as jev

    sent = {}

    def fake_post(url, payload, *, headers, timeout_s):
        sent.update(url=url, payload=payload, headers=headers, timeout_s=timeout_s)
        return {"answers": {"decision": {
            "choice": "assist", "probabilities": {"zero": 0.02, "resist": 0.03,
                                                     "assist": 0.95}, "confidence": 0.95}}}

    monkeypatch.setattr(jev, "post_json", fake_post)
    g = fresh(backend="jev", api_key="test-key")
    for s in frames("walk"):
        g.feed(s)
    d = g.tick(100.0, current_policy="zero", armed=True,
               tripped=None, legs_offline=False)
    assert d.backend == "jev" and d.want == "assist" and d.confidence == 0.95
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone"
    assert sent["payload"]["questions"]["decision"]["type"] == "choice"
    assert sent["headers"]["Authorization"] == "Bearer test-key"


def test_auto_backend_never_routes_telemetry_to_generic_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    g = fresh(backend="auto")
    assert g.decider.chain == ("jev", "rules")
    for s in frames("walk"):
        g.feed(s)
    d = g.tick(100.0, current_policy="zero", armed=True,
               tripped=None, legs_offline=False)
    assert d.backend == "rules"


def test_unsafe_state_forces_zero_without_remote_call(monkeypatch):
    g = fresh(backend="jev", autopilot=True)
    for s in frames("walk"):
        g.feed(s)
    monkeypatch.setattr(g.decider, "choice", lambda *a, **kw: pytest.fail("remote called"))
    g._last_switch = 99.0  # hold must never suppress an emergency zero
    d = g.tick(100.0, current_policy="assist", armed=False,
               tripped=None, legs_offline=False)
    assert d.applied == "zero" and d.gain == 0.0
    assert d.autopilot and d.held_by == ""


def test_stale_stream_forces_zero_without_remote_call(monkeypatch):
    g = fresh(backend="jev", background=True, autopilot=True)
    for s in frames("walk"):
        g.feed(s)
    monkeypatch.setattr(g.decider, "choice", lambda *a, **kw: pytest.fail("remote called"))
    d = g.tick(100.0, current_policy="assist", armed=True,
               tripped=None, legs_offline=False, sample_age_s=0.8)
    assert d.applied == "zero" and d.gain == 0.0


def test_background_request_does_not_block_and_discards_stale_answer(monkeypatch):
    from threading import Event
    from time import perf_counter

    release = Event()
    g = fresh(backend="jev", background=True, autopilot=True)
    for s in frames("walk"):
        g.feed(s)
    answer = Decider("rules").choice(state_for("walk"), "策略？", OPTIONS,
                                     rules=policy_weights)

    def slow_choice(*args, **kwargs):
        release.wait(1.0)
        return answer

    monkeypatch.setattr(g.decider, "choice", slow_choice)
    started = perf_counter()
    assert g.tick(100.0, current_policy="zero", armed=True,
                  tripped=None, legs_offline=False, sample_age_s=0.0) is None
    assert perf_counter() - started < 0.25
    assert g.tick(101.0, current_policy="zero", armed=True,
                  tripped=None, legs_offline=False, sample_age_s=0.0) is None
    release.set()
    try:
        assert g._pending.result(timeout=1.0) == answer
        assert g.tick(102.0, current_policy="zero", armed=True,
                      tripped=None, legs_offline=False, sample_age_s=0.0) is None
        assert g.n_applied == 0
    finally:
        g.close()


def test_wearer_trajectory_is_deterministic_and_bounded():
    for name, spec in GAITS.items():
        a = angles(spec, 0.37)
        assert a == angles(spec, 0.37)
        for leg, (pos, _vel) in a.items():
            assert abs(pos) <= spec.amp_deg * math.pi / 180 + 1e-9, f"{name}/{leg} 超出摆幅"
