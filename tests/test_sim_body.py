"""数字义体测试：接口与真机一致、行为可复现、参数来自真实辨识。"""
from __future__ import annotations

import time

import pytest

from bridge.exo import ExoBridge
from bridge.plant import DEG2RAD, LegLoad
from bridge.sim import SimBridge, identify_from_recording

# runtime/service.py 和 tools/* 用到的全部门面
FACADE = ["open", "ping", "version", "enable", "disable", "close", "on_sample", "on_event",
          "set_torque", "set_ramp", "trip", "rearm", "stream_hz"]
ATTRS = ["latest", "commanded", "log_path", "tripped", "legs_offline", "enabled",
         "n_reconnects", "ramp_nm_per_s"]


def test_sim_matches_real_bridge_facade():
    """少一个方法，拔线换身体那一下就会炸。"""
    for name in FACADE:
        assert callable(getattr(SimBridge, name, None)), f"SimBridge 缺方法 {name}"
        assert callable(getattr(ExoBridge, name, None)), f"ExoBridge 缺方法 {name}"
    b = SimBridge(log_dir=None)
    for name in ATTRS:
        assert hasattr(b, name), f"SimBridge 缺属性 {name}"
    assert hasattr(b, "_reconnecting"), "service 会读这个字段"


def test_params_come_from_real_recording():
    p = identify_from_recording()
    assert set(p) == {"L", "R"}
    for leg, v in p.items():
        assert "breakaway" in v.source or "兜底" in v.source
        assert 0.0 < v.coulomb_nm < 2.0, f"{leg} 静摩擦量级不对：{v.coulomb_nm}"
        assert abs(v.bias_nm) < 1.0, f"{leg} 偏置量级不对：{v.bias_nm}"


def test_plant_gravity_pulls_toward_neutral():
    load = LegLoad()
    assert load.external_nm(30 * DEG2RAD, 0.0) < 0      # 抬起来时重力往回拉
    assert load.external_nm(-30 * DEG2RAD, 0.0) > 0
    assert load.external_nm(0.0, 0.0) == pytest.approx(0.0, abs=1e-9)


def test_plant_end_stops_push_back():
    load = LegLoad()
    beyond = load.max_rad + 5 * DEG2RAD
    assert load.external_nm(beyond, 0.0) < -1.0, "越过上限位必须被推回来"
    pos, vel = load.clamp(beyond, 1.0)
    assert pos == load.max_rad and vel == 0.0


@pytest.mark.slow
def test_torque_moves_the_body_and_stops_at_limits():
    b = SimBridge(log_dir=None).open()
    b.enable(send_torque=True)
    try:
        time.sleep(1.2)                         # stream_hz 统计最近 1 秒，要先攒满一窗
        assert b.stream_hz() > 100, f"义体要按真机节奏出数据，实测 {b.stream_hz()} Hz"
        b.set_torque(-1.5, 1.5)                 # 两腿向上（UP_SIGN：左负右正）
        time.sleep(2.5)
        assert b.latest.ldeg < -60 and b.latest.rdeg > 60, "1.5 Nm 应该能把腿抬起来"
        assert b.latest.ldeg >= -109 and b.latest.rdeg <= 106, "不准穿出机械限位"
    finally:
        b.close()


def test_safety_check_is_called_and_can_trip():
    seen = []

    def check(s):
        seen.append(s)
        return "测试注入急停" if len(seen) > 20 else None

    b = SimBridge(log_dir=None, safety_check=check).open()
    b.enable(send_torque=True)
    try:
        time.sleep(0.5)
        assert b.tripped == "测试注入急停"
        assert b.commanded == (0.0, 0.0)
    finally:
        b.close()
