"""串口协议与纯计算部分的特征测试。

这些是重构 bridge/ 时的安全网：协议解析、端口发现、限幅与斜坡都是纯逻辑，
拆文件前先把行为钉死，拆完必须一字不差。
"""
from __future__ import annotations

import math

import pytest

from bridge.serial_io import (
    BAUD,
    DEFAULT_LIMIT_NM,
    DEFAULT_RAMP_NM_PER_S,
    FIRMWARE_LIMIT_NM,
    SEND_HZ,
    STALL_S,
    STREAM_FIELDS,
    WATCHDOG_S,
    Sample,
    parse_stream_line,
)

# 协议文档《深圳黑客松2026串口协议》里的真实一帧
REAL_FRAME = (
    "S:1883919,17.345,-4.400,116.870,0.516,1.769,0.918,"
    "-0.304,-0.076,1.019,100.849,-1.488,-0.264,0.400,0.000"
)


def test_constants_match_protocol_doc():
    """这些常量直接来自协议文档，改动必须是有意的。"""
    assert BAUD == 3_000_000
    assert FIRMWARE_LIMIT_NM == 7.5
    assert WATCHDOG_S == pytest.approx(0.100)
    assert DEFAULT_LIMIT_NM == 2.0
    assert SEND_HZ == 100
    assert DEFAULT_RAMP_NM_PER_S == 3.0
    assert STALL_S == pytest.approx(0.35)
    assert STREAM_FIELDS == (
        "ms", "pitch", "roll", "yaw", "gx", "gy", "gz",
        "ax", "ay", "az", "kpa", "ldeg", "rdeg", "ldps", "rdps",
    )


def test_parse_real_frame():
    s = parse_stream_line(REAL_FRAME, host_t=1.0, cmd_l=0.5, cmd_r=-0.5)
    assert s is not None
    assert s.host_t == 1.0
    assert s.ms == 1883919
    assert s.pitch == 17.345 and s.roll == -4.400 and s.yaw == 116.870
    assert s.gx == 0.516 and s.gy == 1.769 and s.gz == 0.918
    assert s.ax == -0.304 and s.ay == -0.076 and s.az == 1.019
    assert s.kpa == 100.849
    assert s.ldeg == -1.488 and s.rdeg == -0.264
    assert s.ldps == 0.400 and s.rdps == 0.000
    assert s.cmd_l == 0.5 and s.cmd_r == -0.5


@pytest.mark.parametrize("line", [
    "OK,T,0.000,0.000",          # 力矩回执，不是数据帧
    "PONG",
    "OK,VERSION,2.9.99.1",
    "ERR,NOT_ENABLED",
    "S:1,2,3",                   # 字段数不足
    "S:" + ",".join(["1"] * 16),  # 字段数过多
    "S:abc,1,2,3,4,5,6,7,8,9,10,11,12,13,14",  # 非数字
    "",
    "随便一行中文",
])
def test_parse_rejects_non_frames(line):
    assert parse_stream_line(line, host_t=0.0) is None


def test_sample_field_order_is_frame_order():
    """Sample 的字段顺序必须与 S: 帧一致，否则按位置构造会错位。"""
    from dataclasses import fields

    names = [f.name for f in fields(Sample)]
    assert names[0] == "host_t"
    assert tuple(names[1:16]) == STREAM_FIELDS
    assert names[16:] == ["cmd_l", "cmd_r"]


def test_saturated_velocity_is_parsed_not_dropped():
    """编码器饱和值 ±3276.7 要如实解析出来，由上层决定怎么处理。"""
    line = "S:1,0,0,0,0,0,0,0,0,1,100,0,0,3276.7,-3276.7"
    s = parse_stream_line(line, host_t=0.0)
    assert s is not None and s.ldps == 3276.7 and s.rdps == -3276.7


def test_ramp_step_math():
    """斜坡：每个发送周期允许的最大变化 = 速率 / 发送频率。"""
    from bridge.serial_io import ExoBridge

    b = ExoBridge.__new__(ExoBridge)          # 不开串口，只验算数
    b.send_period = 1.0 / SEND_HZ
    b.set_ramp(12.0)
    assert b.ramp_step == pytest.approx(12.0 / SEND_HZ)
    assert b.ramp_nm_per_s == pytest.approx(12.0)
    b.set_ramp(0.0)                            # 下限保护
    assert b.ramp_nm_per_s == pytest.approx(0.05)


def test_torque_clamp_math():
    """软限幅：目标力矩按 torque_limit 双向截断；软限幅本身不得超过固件硬限。"""
    import threading

    from bridge.serial_io import ExoBridge

    b = ExoBridge.__new__(ExoBridge)
    b.torque_limit = min(2.0, FIRMWARE_LIMIT_NM)
    b._lock = threading.Lock()
    b._target = (0.0, 0.0)
    for left, right, want in [
        (0.5, -0.5, (0.5, -0.5)),
        (99.0, -99.0, (2.0, -2.0)),
        (0.0, 0.0, (0.0, 0.0)),
    ]:
        b.set_torque(left, right)
        assert b._target == want


def test_find_port_globs_are_platform_aware():
    """macOS 用 cu.*，Linux 用 ttyUSB / by-id；两边都不准少。"""
    import sys

    from bridge.serial_io import PORT_GLOBS

    joined = " ".join(PORT_GLOBS)
    if sys.platform == "darwin":
        assert "/dev/cu.usbserial*" in PORT_GLOBS
        assert "cu.usbmodem" in joined
    else:
        assert "/dev/ttyUSB*" in PORT_GLOBS
        assert "by-id" in joined


def test_work_integral_sign_convention():
    """机械功 = τ·ω；阻尼（τ 与 ω 反号）必须得到负功。"""
    tau, omega_dps, dt = -0.5, 120.0, 0.01
    work = tau * math.radians(omega_dps) * dt
    assert work < 0
