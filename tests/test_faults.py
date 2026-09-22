"""故障注入：义体上按需复现真机故障，事件序列必须可预测、可重放。"""
from __future__ import annotations

import pytest

from bridge.faults import FAULT_KINDS, FaultInjector
from bridge.protocol import Sample

BASE = dict(ms=0.0, pitch=0.0, roll=0.0, yaw=0.0, gx=0.0, gy=0.0, gz=0.0,
            ax=0.0, ay=0.0, az=1.0, kpa=101.0, ldeg=10.0, rdeg=-10.0, ldps=5.0, rdps=-5.0)


def frame(t: float) -> Sample:
    return Sample(host_t=t, **BASE)


def run(inj: FaultInjector, times) -> list[tuple[float, Sample | None, list[str]]]:
    return [(t, *inj.step(t, frame(t))) for t in times]


def test_unknown_fault_is_rejected_at_arm_time():
    with pytest.raises(ValueError):
        FaultInjector().arm("没这个故障", now=0.0)


def test_legs_offline_zeroes_the_joints_and_comes_back():
    inj = FaultInjector()
    inj.arm("legs_offline", now=0.0, delay_s=0.1, duration_s=0.3)
    out = run(inj, [0.0, 0.15, 0.25, 0.45, 0.6])
    assert out[0][1].ldeg == 10.0 and out[0][2] == []          # 还没开始
    assert out[1][2] == ["legs_offline"]                       # 进入
    assert all(getattr(out[i][1], f) == 0.0 for i in (1, 2)
               for f in ("ldeg", "rdeg", "ldps", "rdps"))      # 关节全零
    assert out[3][2] == ["legs_online"]                        # 自动恢复
    assert out[4][1].ldeg == 10.0 and out[4][2] == []          # 恢复后干净


def test_port_lost_drops_frames_entirely():
    inj = FaultInjector()
    inj.arm("port_lost", now=0.0, delay_s=0.0, duration_s=0.2)
    out = run(inj, [0.0, 0.1, 0.25])
    assert out[0][1] is None and out[0][2] == ["stall"]
    assert out[1][1] is None                                   # 整段不出帧
    assert out[2][2] == ["reconnected"] and out[2][1] is not None


def test_tilt_pushes_pitch_past_the_wearing_threshold():
    from control.profiles import WEARING
    inj = FaultInjector()
    inj.arm("tilt", now=0.0, delay_s=0.0, duration_s=0.2)
    s, _ = inj.step(0.1, frame(0.1))
    assert abs(s.pitch) > WEARING.tilt_trip_deg


def test_injection_is_deterministic():
    """同一段注入脚本跑两遍，事件序列必须完全一样（不碰 time.time）。"""
    def once():
        inj = FaultInjector()
        inj.arm("legs_offline", now=0.0, delay_s=0.1, duration_s=0.2)
        inj.arm("tilt", now=0.0, delay_s=0.5, duration_s=0.2)
        return [(t, ev) for t, _, ev in run(inj, [i * 0.05 for i in range(20)])]
    assert once() == once()


def test_no_fault_armed_is_a_pass_through():
    inj = FaultInjector()
    s, ev = inj.step(1.0, frame(1.0))
    assert ev == [] and s.ldeg == 10.0 and inj.n_injected == 0


def test_every_kind_is_documented():
    """ctl 和仪表盘都从 FAULT_KINDS 取说明，新增故障必须同时写说明。"""
    inj = FaultInjector()
    for kind in FAULT_KINDS:
        inj.arm(kind, now=0.0)
        assert FAULT_KINDS[kind].strip()
