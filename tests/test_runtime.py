"""runtime/ 的纯逻辑测试：事件翻译、状态格式化、命令分发、斜坡规则。

这些原来都埋在 tools/service.py 的 main() 里，没法测。拆出来后每一条都能钉死。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import control.policies as P
from control.safety import PROFILES
from runtime import commands, events, status
from runtime.session import Session


# ---------- 事件翻译 ----------

def test_trip_event_is_translated_with_recovery_hint():
    msg, level = events.describe("trip:腰部加速度 3.1 g > 2.5 g")
    assert level == "err"
    assert "急停锁存" in msg and "3.1 g" in msg
    assert "arm" in msg, "急停提示必须告诉人怎么恢复"


@pytest.mark.parametrize("ev,level", [
    ("legs_offline", "warn"), ("legs_online", "ok"),
    ("stall", "warn"), ("reconnected", "ok"),
    ("stream_slow", "warn"), ("reconnect_failed", "err"),
])
def test_known_events_have_human_text(ev, level):
    msg, lv = events.describe(ev)
    assert lv == level and msg != ev and msg.strip()


def test_unknown_event_passes_through():
    assert events.describe("某个新事件") == ("某个新事件", "info")


def test_legs_offline_message_tells_the_fix():
    msg, _ = events.describe("legs_offline")
    assert "短按" in msg and "长按" in msg and "不用拔线" in msg


# ---------- 状态 ----------

@pytest.mark.parametrize("kw,want", [
    (dict(tripped="x", armed=True, legs_offline=False, reconnecting=False), "TRIPPED"),
    (dict(tripped=None, armed=False, legs_offline=False, reconnecting=False), "TRIPPED"),
    (dict(tripped=None, armed=True, legs_offline=True, reconnecting=False), "LEGS_OFF"),
    (dict(tripped=None, armed=True, legs_offline=False, reconnecting=True), "RECONN"),
    (dict(tripped=None, armed=True, legs_offline=False, reconnecting=False), "ARMED"),
])
def test_device_state_priority(kw, want):
    assert status.device_state(**kw) == want


def test_console_line_is_stable():
    line = status.console_line(
        state="ARMED", policy="resist", gain=0.5, hz=180.0,
        ldeg=-1.23, rdeg=45.6, ldps=-7.0, rdps=8.0,
        tau_l=-0.5, tau_r=0.25, scale=0.75, work_J=-12.34, clock="12:34:56")
    assert line == ("12:34:56    ARMED  resist  0.50  180 |   -1.2   45.6 |     -7      8 | "
                    " -0.50  +0.25 | 0.75  -12.3")


def test_status_file_write_is_atomic(tmp_path: Path):
    p = tmp_path / "status.json"
    status.write_status_file(str(p), {"a": 1})
    assert json.loads(p.read_text())["a"] == 1
    assert not (tmp_path / "status.json.tmp").exists(), "临时文件必须被改名掉"


def test_status_file_write_never_raises(tmp_path: Path):
    status.write_status_file(str(tmp_path / "no" / "such" / "dir" / "s.json"), {"a": 1})


# ---------- 斜坡（项目规则第 1 条） ----------

def test_wearing_profile_halves_the_ramp():
    table = Session(profile=PROFILES["table"], ramp_cap_nm_s=3.0)
    wear = Session(profile=PROFILES["wearing"], ramp_cap_nm_s=3.0)
    for s in (table, wear):
        s.policy = P.make_policy("resist", 0.5, 1.5)
    assert table.ramp_for_current_policy() == 3.0
    assert wear.ramp_for_current_policy() == 0.75
    assert wear.ramp_for_current_policy() < table.ramp_for_current_policy()


def test_torque_policy_has_the_slowest_ramp():
    s = Session(profile=PROFILES["table"], ramp_cap_nm_s=12.0)
    s.policy = P.TorquePolicy(0.0, 0.8, 10.0, 1.5)
    assert s.ramp_for_current_policy() == 1.0, "直接力矩必须是 1 Nm/s"


def test_global_cap_wins():
    s = Session(profile=PROFILES["table"], ramp_cap_nm_s=0.5)
    s.policy = P.make_policy("resist", 0.5, 1.5)
    assert s.ramp_for_current_policy() == 0.5


# ---------- 命令分发 ----------

class FakeBridge:
    def __init__(self):
        self.tripped = None
        self.ramp = None
        self.trips: list[str] = []
        self.rearmed = False

    def set_ramp(self, v):
        self.ramp = v

    def trip(self, why):
        self.trips.append(why)
        self.tripped = why

    def rearm(self, send_torque=True):
        self.rearmed = True
        self.tripped = None
        return "OK,ENABLE"


def _session(profile="table"):
    return Session(profile=PROFILES[profile], ramp_cap_nm_s=3.0)


def test_policy_command_switches_and_applies_ramp():
    s, b, logs = _session(), FakeBridge(), []
    commands.apply({"op": "policy", "policy": "resist", "gain": 0.5, "max": 1.5},
                   session=s, bridge=b, log=lambda m, lv="info": logs.append((m, lv)))
    assert s.policy.name == "resist" and b.ramp == 3.0
    assert any(lv == "ok" for _, lv in logs)


def test_policy_is_ignored_while_tripped():
    s, b, logs = _session(), FakeBridge(), []
    s.armed = False
    commands.apply({"op": "policy", "policy": "assist", "gain": 0.2, "max": 0.8},
                   session=s, bridge=b, log=lambda m, lv="info": logs.append((m, lv)))
    assert s.policy.name == "zero", "急停锁存时不准切策略"
    assert any(lv == "warn" for _, lv in logs)


def test_hold_and_torque_are_table_only():
    for op, extra in [("hold", {"R": 30.0}), ("torque", {"L": 0.0, "R": 0.5})]:
        s, b, logs = _session("wearing"), FakeBridge(), []
        commands.apply({"op": op, **extra}, session=s, bridge=b,
                       log=lambda m, lv="info": logs.append((m, lv)))
        assert s.policy.name == "zero", f"{op} 不该在穿戴档生效"
        assert any(lv == "err" for _, lv in logs)


def test_estop_then_arm():
    s, b, logs = _session(), FakeBridge(), []
    log = lambda m, lv="info": logs.append((m, lv))
    commands.apply({"op": "estop"}, session=s, bridge=b, log=log)
    assert b.trips == ["操作员急停"]
    s.armed = False
    commands.apply({"op": "arm"}, session=s, bridge=b, log=log)
    assert b.rearmed and s.armed and s.policy.name == "zero"


def test_quit_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        commands.apply({"op": "quit"}, session=_session(), bridge=FakeBridge(),
                       log=lambda *a, **k: None)


def test_unknown_op_is_logged_not_raised():
    logs = []
    commands.apply({"op": "涨停"}, session=_session(), bridge=FakeBridge(),
                   log=lambda m, lv="info": logs.append((m, lv)))
    assert logs and logs[0][1] == "warn"


def test_every_known_op_has_a_handler():
    assert set(commands.KNOWN_OPS) == {
        "policy", "zero", "hold", "torque", "estop", "arm", "reload", "quit",
        "fault", "recall", "gait"}
