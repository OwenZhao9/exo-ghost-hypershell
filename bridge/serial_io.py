"""兼容层：老代码都写的 `from bridge.serial_io import ...`，保持不变。

真正的实现已经按职责拆开了：

    bridge/protocol.py   数据帧、常量、解析（纯）
    bridge/ports.py      跨平台设备发现（纯）
    bridge/limits.py     限幅与斜坡（纯）
    bridge/logger.py     CSV 落盘
    bridge/exo.py        ExoBridge：串口收发、续发、重连、生命周期

新代码请直接从上面那些模块 import；本文件只做转发，不放任何逻辑。
"""
from __future__ import annotations

from .exo import ExoBridge, default_safety
from .limits import clamp, effective_limit, ramp_step, step_toward
from .logger import SessionLogger
from .ports import PORT_GLOBS, PORT_GLOBS_DARWIN, PORT_GLOBS_LINUX, find_port, permission_hint
from .protocol import (
    BAUD,
    DEFAULT_LIMIT_NM,
    DEFAULT_RAMP_NM_PER_S,
    DPS_SATURATION,
    FIRMWARE_LIMIT_NM,
    SEND_HZ,
    STALL_S,
    STREAM_FIELDS,
    WATCHDOG_S,
    Sample,
    parse_stream_line,
)

__all__ = [
    "ExoBridge", "default_safety", "Sample", "parse_stream_line",
    "find_port", "permission_hint", "PORT_GLOBS", "PORT_GLOBS_DARWIN", "PORT_GLOBS_LINUX",
    "clamp", "effective_limit", "ramp_step", "step_toward", "SessionLogger",
    "BAUD", "FIRMWARE_LIMIT_NM", "DEFAULT_LIMIT_NM", "DEFAULT_RAMP_NM_PER_S",
    "SEND_HZ", "WATCHDOG_S", "STALL_S", "STREAM_FIELDS", "DPS_SATURATION",
]
