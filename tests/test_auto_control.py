"""An agent recommendation must pass the latest local safety gate."""
from types import SimpleNamespace

from agent.auto_control import next_command


FRESH_WALK = {
    "usable": True, "armed": True, "tripped": "", "legs_offline": False,
    "hz": 180.0, "cadence_hz": 1.0, "antiphase": 0.95, "rom_deg": 30.0,
}


def action(applied="assist", gain=0.3, confidence=0.9, **changes):
    state = {**FRESH_WALK, **changes}
    return next_command(SimpleNamespace(applied=applied, gain=gain,
                                        confidence=confidence),
                        current_policy="zero", current_gain=0.0,
                        fresh=state, sample_recent=True, quiet=False,
                        min_confidence=0.55)


def test_model_assist_can_only_start_with_fresh_gait_and_small_output():
    assert action() == {"op": "policy", "policy": "assist", "gain": 0.1, "max": 0.5}
    assert action(cadence_hz=0.0) is None
    assert action(legs_offline=True) is None
    assert action(hz=40.0) is None


def test_unsafe_change_while_assisting_requests_zero():
    d = SimpleNamespace(applied="assist", gain=0.3, confidence=0.9)
    command = next_command(d, current_policy="assist", current_gain=0.1,
                           fresh={**FRESH_WALK, "tripped": "operator"},
                           sample_recent=True, quiet=False, min_confidence=0.55)
    assert command == {"op": "zero"}


def test_stale_or_quiet_sensor_never_starts_resistance():
    d = SimpleNamespace(applied="resist", gain=0, confidence=1)
    for recent, quiet in ((False, False), (True, True)):
        assert next_command(d, current_policy="zero", current_gain=0,
                            fresh=FRESH_WALK, sample_recent=recent,
                            quiet=quiet, min_confidence=0.55) is None
    assert action(applied="resist") == {
        "op": "policy", "policy": "resist", "gain": 0.3, "max": 0.5}
