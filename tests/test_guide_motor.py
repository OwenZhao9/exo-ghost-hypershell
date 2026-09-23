"""Motor demo: direction mapping, timed zero, and command gates."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from control.guide_cue import CUE_ANGLE_DEG, CUE_MAX_NM, GuideCuePolicy
from control.safety import PROFILES
from runtime import commands
from runtime.session import Session


def sample(**changes):
    values = dict(ldeg=8.0, rdeg=-7.0, ldps=0.0, rdps=0.0, host_t=time.time())
    values.update(changes)
    return SimpleNamespace(**values)


class Bridge:
    def __init__(self, reading=None):
        self.latest = reading or sample()
        self.ramp = None
        self.legs_offline = False

    def set_ramp(self, value):
        self.ramp = value


@pytest.mark.parametrize("direction,leg,target", [
    ("right", "L", 8.0 - CUE_ANGLE_DEG),
    ("left", "R", -7.0 + CUE_ANGLE_DEG),
])
def test_cue_lifts_opposite_leg_and_expires_to_zero(direction, leg, target):
    now = [0.0]
    policy = GuideCuePolicy(direction, 8.0, -7.0, clock=lambda: now[0])
    assert policy.leg == leg and policy.target_deg == target
    assert policy.max_torque == CUE_MAX_NM
    assert policy.ramp_nm_per_s == 1.0
    reading = sample()
    policy.torque(reading)
    reading.host_t += 0.1
    left, right = policy.torque(reading)
    assert abs(left) <= CUE_MAX_NM and abs(right) <= CUE_MAX_NM
    assert (right == 0.0 if leg == "L" else left == 0.0)
    assert (left < 0 if leg == "L" else right > 0)
    now[0] = 4.0
    assert policy.expired() and policy.torque(reading) == (0.0, 0.0)


def test_cue_rejects_targets_near_observed_joint_end_range():
    with pytest.raises(ValueError, match="行程末端"):
        GuideCuePolicy("right", -89.0, 0.0)
    with pytest.raises(ValueError, match="行程末端"):
        GuideCuePolicy("left", 0.0, 79.0)


def run(direction="right", *, profile="table", enabled=True, reading=None, policy="zero"):
    session = Session(profile=PROFILES[profile], ramp_cap_nm_s=1.5,
                      guide_motor_demo=enabled)
    if policy != "zero":
        from control.policies import make_policy
        session.policy = make_policy(policy, 0.3, 1.0)
    bridge = Bridge(reading)
    logs = []
    commands.apply({"op": "guide_cue", "direction": direction},
                   session=session, bridge=bridge,
                   log=lambda message, level="info": logs.append((message, level)))
    return session, bridge, logs


def test_live_cue_requires_explicit_table_demo_and_resting_legs():
    session, bridge, _ = run()
    assert session.policy.name == "guide_cue"
    assert bridge.ramp == 1.0
    for options in ({"enabled": False}, {"profile": "wearing"},
                    {"direction": "unknown"}, {"policy": "assist"},
                    {"reading": sample(ldps=25.0)},
                    {"reading": sample(ldps=float("nan"))},
                    {"reading": sample(host_t=time.time() - 2)}):
        session, _, _ = run(**options)
        assert session.policy.name != "guide_cue"
    session = Session(profile=PROFILES["table"], ramp_cap_nm_s=1.5,
                      guide_motor_demo=True)
    bridge = Bridge()
    bridge.legs_offline = True
    commands.apply({"op": "guide_cue", "direction": "right"},
                   session=session, bridge=bridge, log=lambda *_: None)
    assert session.policy.name == "zero"
