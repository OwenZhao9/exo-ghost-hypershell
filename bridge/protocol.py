"""串口协议：常量、数据帧、解析。

**纯逻辑，无 IO、无线程、无状态**——这是整个 bridge/ 里最容易测、最容易复用的一层。
协议来自《深圳黑客松2026串口协议.docx》（固件 2.9.99.1）：

    USB CDC，3,000,000 baud，8N1；一行一条命令，\n 结尾
    PING              -> PONG
    VERSION           -> OK,VERSION,2.9.99.1
    ENABLE            -> OK,ENABLE        使能力矩并开始数据流
    DISABLE           -> OK,DISABLE       力矩清零并停止数据流
    T,<left>,<right>  -> OK,T,<l>,<r>     左右解耦力矩，Nm，固件限幅 ±7.5
    看门狗：100 ms 未续发 T，力矩自动清零（实测约 115 ms）
    数据流：S:<ms>,<pitch>,<roll>,<yaw>,<gx>,<gy>,<gz>,<ax>,<ay>,<az>,<kPa>,<Ldeg>,<Rdeg>,<Ldps>,<Rdps>
    实测频率约 180 Hz（协议标称 200）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

BAUD = 3_000_000
FIRMWARE_LIMIT_NM = 7.5          # 固件硬限幅，超过不认
DEFAULT_LIMIT_NM = 2.0           # 我们自己的软限幅（演示阶段）
DEFAULT_RAMP_NM_PER_S = 3.0      # 斜坡默认 3 Nm/s（项目规则：任何力都要慢慢加；各策略再按需收紧）
SEND_HZ = 100                    # 力矩续发频率（协议建议 200，允许 10–500；实测 200 Hz 长跑偶发停流，用 100 Hz 减半应答流量）
WATCHDOG_S = 0.100               # 固件看门狗（实测约 115 ms）
STALL_S = 0.35                   # 数据流断流判定（正常帧间隔 ~6 ms）

DPS_SATURATION = 3276.7          # 关节角速度饱和值（int16/10）；上层据此丢弃尖峰

STREAM_FIELDS = ("ms", "pitch", "roll", "yaw", "gx", "gy", "gz",
                 "ax", "ay", "az", "kpa", "ldeg", "rdeg", "ldps", "rdps")


@dataclass
class Sample:
    """一帧传感器数据。字段顺序必须与 S: 帧一致（按位置构造）。"""
    host_t: float          # 电脑侧时间 time.time()
    ms: float              # 主板时间 ms
    pitch: float; roll: float; yaw: float        # 穿戴系欧拉角 °
    gx: float; gy: float; gz: float              # 腰部陀螺仪 °/s
    ax: float; ay: float; az: float              # 腰部加速度 g
    kpa: float                                   # 气压 kPa
    ldeg: float; rdeg: float                     # 左右髋关节角度 °
    ldps: float; rdps: float                     # 左右髋关节角速度 °/s
    cmd_l: float = 0.0     # 当时我们下发的左力矩 Nm
    cmd_r: float = 0.0


def parse_stream_line(line: str, host_t: float,
                      cmd_l: float = 0.0, cmd_r: float = 0.0) -> Optional[Sample]:
    """解析一行 S: 帧；不是 S: 帧或字段数不对返回 None。

    FireWater 风格：按行、逗号分隔、换行是帧结束符。
    """
    if not line.startswith("S:"):
        return None
    parts = line[2:].split(",")
    if len(parts) != len(STREAM_FIELDS):
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    return Sample(host_t, *vals, cmd_l=cmd_l, cmd_r=cmd_r)
