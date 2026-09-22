"""反射层内核的性质测试。

安全判定的内核换成了 fly-reflex，它有两个后端：
  rules    —— 逐条阈值，确定性、可解释，生产默认
  spiking  —— 受果蝇逃逸通路（LC4/LPLC2 → DNp01）启发的小型 LIF 网络

这里不录基准（基准在 test_safety_regression.py），只钉住几条**性质**：
两个后端在同一份真实录制上应该得出一致的结论，且都不自己锁存。
"""
from __future__ import annotations

import pytest

from conftest import load_samples
from bridge.serial_io import Sample
from control.profiles import PROFILES
from control.reflex_rules import TRIP_SIGNALS, build_rules, tilt_deg
from control.safety import SafetyMonitor


def first_trip(mon: SafetyMonitor, samples) -> tuple[int, str] | None:
    for i, s in enumerate(samples):
        why = mon.trip(s)
        if why:
            return i, why
    return None


# ---------------------------------------------------------------- 规则的组装

def test_table_profile_has_no_tilt_rule():
    """桌面档 tilt_trip_deg=None：设备侧躺放着不该急停。"""
    ids = {r.id for r in build_rules(PROFILES["table"], 2.0)}
    assert "tilt_pitch" not in ids and "tilt_roll" not in ids
    assert {"acc", "gyro", "joint_l", "joint_r", "session"} <= ids


def test_every_rule_id_maps_to_a_stable_signal():
    """回归基准按信号类别比较，任何新规则都必须在 TRIP_SIGNALS 里登记。"""
    for profile in PROFILES.values():
        for r in build_rules(profile, 2.0):
            assert r.id in TRIP_SIGNALS, f"规则 {r.id} 没登记信号类别"


def test_no_rule_latches_inside_the_library():
    """锁存是 ExoBridge 的职责。库内锁存会让 trip() 变成有状态的，破坏分工。"""
    for profile in PROFILES.values():
        for r in build_rules(profile, 2.0):
            assert r.action.value == "soft", f"规则 {r.id} 不该用 HARD_STOP"


def test_tilt_deg_is_the_larger_absolute_axis():
    assert tilt_deg({"pitch": -70.0, "roll": 3.0}) == 70.0
    assert tilt_deg({"pitch": 3.0, "roll": -70.0}) == 70.0
    assert tilt_deg({}) == 0.0                      # 缺 key 不抛异常


# ---------------------------------------------------------------- 两个后端的一致性

@pytest.mark.parametrize("backend", ["rules", "spiking"])
def test_backend_trips_on_the_fall_in_real_recordings(sample_files, backend):
    """三段真实录制里设备都被扳过 45° 倾角，穿戴档两个后端都该拦住。"""
    for path in sample_files:
        mon = SafetyMonitor(PROFILES["wearing"], backend=backend)
        hit = first_trip(mon, load_samples(path))
        assert hit is not None, f"{path.name} / {backend} 应该触发却没触发"
        assert mon.stats()["backend"] == backend


def test_two_backends_agree_within_a_few_frames(sample_files):
    """机制完全不同（阈值 vs 脉冲网络），但在真实数据上应当几乎同时发放。

    容差 5 帧（≈28 ms @180 Hz）：脉冲后端要积累膜电位，天然晚一点点。
    """
    for path in sample_files:
        samples = load_samples(path)
        a = first_trip(SafetyMonitor(PROFILES["wearing"], backend="rules"), samples)
        b = first_trip(SafetyMonitor(PROFILES["wearing"], backend="spiking"), samples)
        assert a and b
        assert 0 <= b[0] - a[0] <= 5, f"{path.name}: 规则 {a[0]} 帧 / 脉冲 {b[0]} 帧，差太多"
        assert "tilt" in b[1], f"{path.name}: 脉冲后端认错了主导信号 —— {b[1]}"


# ---------------------------------------------------------------- 运行期不抛异常

def test_missing_signal_does_not_raise(monkeypatch):
    """契约 0.4：运行期永不抛异常到控制环。少了信号只能降级，不能炸。"""
    mon = SafetyMonitor(PROFILES["wearing"], warmup_s=0.0)
    monkeypatch.setattr(mon, "_sensors", lambda s, now: {})     # 什么信号都没有
    base = dict(ms=0.0, pitch=0.0, roll=0.0, yaw=0.0, gx=0.0, gy=0.0, gz=0.0,
                ax=0.0, ay=0.0, az=1.0, kpa=0.0, ldeg=0.0, rdeg=0.0, ldps=0.0, rdps=0.0)
    assert mon.trip(Sample(host_t=0.0, **base)) is None
    assert mon.assist_scale(Sample(host_t=0.1, **base), 0.0, 0.0) == 1.0
