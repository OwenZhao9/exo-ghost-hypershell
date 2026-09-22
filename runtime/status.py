"""状态快照：终端一行、仪表盘一包、磁盘一份 JSON。

**纯函数**：输入一组读数，输出字符串或 dict，不碰设备也不写文件
（写文件由 `write_status_file` 单独负责，它是唯一有副作用的那个）。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping, Optional

HEADER = (f"{'时间':>8} {'状态':>8} {'策略':>7} {'gain':>5} {'Hz':>4} | "
          f"{'Ldeg':>6} {'Rdeg':>6} | {'Ldps':>6} {'Rdps':>6} | "
          f"{'τL':>6} {'τR':>6} | scale  做功J")


def device_state(*, tripped: Optional[str], armed: bool,
                 legs_offline: bool, reconnecting: bool) -> str:
    """把几个布尔量归纳成一个状态词，仪表盘和终端共用。"""
    if tripped or not armed:
        return "TRIPPED"
    if legs_offline:
        return "LEGS_OFF"
    if reconnecting:
        return "RECONN"
    return "ARMED"


def console_line(*, state: str, policy: str, gain: float, hz: float,
                 ldeg: float, rdeg: float, ldps: float, rdps: float,
                 tau_l: float, tau_r: float, scale: float, work_J: float,
                 clock: Optional[str] = None) -> str:
    """终端每秒一行。"""
    t = clock if clock is not None else time.strftime("%H:%M:%S")
    return (f"{t:>8} {state:>8} {policy:>7} {gain:5.2f} {hz:4.0f} | "
            f"{ldeg:6.1f} {rdeg:6.1f} | {ldps:6.0f} {rdps:6.0f} | "
            f"{tau_l:+6.2f} {tau_r:+6.2f} | {scale:.2f}  {work_J:+.1f}")


def snapshot(*, t: float, state: str, policy: str, gain: float, max_torque: float,
             hz: float, work_J: float, tripped: Optional[str], legs_offline: bool,
             reconnects: int, memory: Optional[Mapping[str, Any]] = None,
             decision: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """推给仪表盘的那一包（不含逐帧读数）。

    `memory` 是 `agent.memory.GhostMemory.snapshot()` 的输出：继承了几条经验、
    最近一次回忆查到了什么。`decision` 是 `agent.decide.GhostDecider.snapshot()`：
    最近一次决策想选什么、置信度多少、有没有被门控拦下。
    没接对应的层时为 None，仪表盘据此隐藏那一栏。
    """
    out = {"t": t, "state": state, "policy": policy, "gain": gain, "max": max_torque,
           "hz": hz, "work_J": work_J, "tripped": tripped,
           "legs_offline": legs_offline, "reconnects": reconnects}
    if memory is not None:
        out["memory"] = dict(memory)
    if decision is not None:
        out["decision"] = dict(decision)
    return out


def full_snapshot(base: Mapping[str, Any], *, ldeg: float, rdeg: float,
                  ldps: float, rdps: float, tau_l: float, tau_r: float,
                  scale: float, log: Optional[str]) -> dict[str, Any]:
    """写到磁盘的那一份：在 snapshot 基础上补逐帧读数，给 `ctl status` 读。"""
    return {**base, "ldeg": ldeg, "rdeg": rdeg, "ldps": ldps, "rdps": rdps,
            "tau_l": tau_l, "tau_r": tau_r, "scale": scale, "log": log}


def write_status_file(path: str, payload: Mapping[str, Any]) -> None:
    """原子写：先写临时文件再改名，读的一方永远看不到半截 JSON。"""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception:
        pass          # 状态文件写失败不该影响控制
