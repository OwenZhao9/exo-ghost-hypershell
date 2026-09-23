"""串口设备发现：跨平台找到外骨骼。

**纯逻辑，只读文件系统**。外骨骼内部是 Silicon Labs CP2102N USB-UART 桥
（VID 0x10C4 / PID 0xEA60），不同系统给的设备名不一样。
"""
from __future__ import annotations

import glob
import os
import sys
from typing import Optional

PORT_GLOBS_DARWIN = (
    "/dev/cu.usbserial*",       # macOS 自带 AppleUSBSLCOM 驱动给的名字
    "/dev/cu.SLAB_USBtoUART*",  # 装了 SiLabs 官方 VCP 驱动时的名字
    "/dev/cu.usbmodem*",        # 原生 USB CDC 设备
)
PORT_GLOBS_LINUX = (
    "/dev/exo",                     # deploy/setup.sh 装的 udev 规则给的固定别名（最稳）
    "/dev/serial/by-id/*CP2102*",   # 按芯片 ID 找，多设备时不会认错
    "/dev/serial/by-id/*Silicon_Labs*",
    "/dev/ttyUSB*",                 # cp210x 驱动给的名字（树莓派 / 香橙派 / 一般 Linux）
    "/dev/ttyACM*",                 # 原生 USB CDC 设备
)
PORT_GLOBS = PORT_GLOBS_DARWIN if sys.platform == "darwin" else PORT_GLOBS_LINUX


def port_candidates(preferred: Optional[str] = None) -> list[str]:
    """列出可用串口；旧端口仍在时优先试旧端口，换号后逐个验证协议。"""
    found = []
    if preferred and os.path.exists(preferred):
        found.append(preferred)
    for g in PORT_GLOBS:
        for cand in sorted(glob.glob(g)):
            port = os.path.realpath(cand) if ("by-id" in g or g == "/dev/exo") else cand
            if port not in found:
                found.append(port)
    return found


def find_port() -> Optional[str]:
    """macOS 用 cu. 不用 tty.（tty. 会等载波信号阻塞）；Linux 优先按 by-id 精确匹配。"""
    return next(iter(port_candidates()), None)


def permission_hint(port: str, err: Exception) -> Optional[str]:
    """Linux 上打不开串口最常见的原因是不在 dialout 组；给一句能照做的提示。"""
    if sys.platform != "darwin" and "Permission denied" in str(err):
        return (f"打不开 {port}：权限不足。把自己加入 dialout 组后重新登录：\n"
                f"  sudo usermod -aG dialout $USER   然后重启或重新登录")
    return None
