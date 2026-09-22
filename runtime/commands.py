"""命令分发：把一条命令（来自 data/cmd.json 或网页）变成对策略/设备的动作。

命令是一个 dict，必有 `op`。所有分支都要么改 `session.policy`，要么调设备，
要么记一条日志——**不在这里直接碰串口线程，也不在这里算力矩**。
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Mapping

import control.policies as P
from control.safety import PROFILES, SafetyMonitor

Log = Callable[..., None]


class CommandError(Exception):
    """命令本身没问题但当前状态不允许执行（例如急停锁存时切策略）。"""


def apply(cmd: Mapping[str, Any], *, session, bridge, log: Log) -> None:
    """执行一条命令。异常一律由调用方兜住，不让它炸掉主循环。"""
    op = cmd.get("op")
    handler = _HANDLERS.get(op)
    if handler is None:
        log(f"未知命令：{op}", "warn")
        return
    handler(cmd, session, bridge, log)
    session.apply_ramp(bridge)


# ---------- 各命令 ----------

def _require_armed(session, log: Log, what: str) -> bool:
    if not session.armed:
        log(f"处于急停锁存，忽略{what}；先 arm", "warn")
        return False
    return True


def _require_table(session, log: Log, what: str) -> bool:
    if session.profile.name != "table":
        log(f"{what}只允许在桌面档使用", "err")
        return False
    return True


def _op_policy(cmd, session, bridge, log):
    if not _require_armed(session, log, "策略命令"):
        return
    session.policy = P.make_policy(cmd["policy"], float(cmd.get("gain", 0.0)),
                                   float(cmd.get("max", 1.5)))
    log(f"策略 → {session.policy.name} gain={session.policy.gain} "
        f"max={session.policy.max_torque}", "ok")


def _op_zero(cmd, session, bridge, log):
    session.policy = P.make_policy("zero", 0.0, 1.5)
    log("策略 → zero", "ok")


def _op_hold(cmd, session, bridge, log):
    if not _require_table(session, log, "hold（位置保持）") or not _require_armed(session, log, "hold"):
        return
    if getattr(session.policy, "name", "") != "hold":
        session.policy = P.HoldPolicy(
            kp=float(cmd.get("kp", 0.08)), kd=float(cmd.get("kd", 0.006)),
            ki=float(cmd.get("ki", 0.04)), max_torque=float(cmd.get("max", 1.5)),
            slew_dps=float(cmd.get("slew", 15.0)))
    for leg in ("L", "R"):
        if leg in cmd:
            session.policy.set_target(leg, cmd[leg])
    log(f"hold 目标 → {session.policy.status()}  (kp={session.policy.kp} "
        f"kd={session.policy.kd} max={session.policy.max_torque})", "ok")


def _op_torque(cmd, session, bridge, log):
    if not _require_table(session, log, "恒定力矩") or not _require_armed(session, log, "恒定力矩"):
        return
    session.policy = P.TorquePolicy(float(cmd.get("L", 0.0)), float(cmd.get("R", 0.0)),
                                    float(cmd.get("seconds", 30.0)), float(cmd.get("max", 1.5)))
    log(f"恒定力矩 → {session.policy.status()}（到期自动归零）", "ok")


def _op_estop(cmd, session, bridge, log):
    bridge.trip("操作员急停")


def _op_arm(cmd, session, bridge, log):
    if not (bridge.tripped or not session.armed):
        log("已是武装状态")
        return
    session.monitor = SafetyMonitor(session.profile)
    session.policy = P.make_policy("zero", 0.0, 1.5)
    try:
        r = bridge.rearm(send_torque=True)
        session.armed = True
        log(f"重新武装 → {r}，策略 zero", "ok")
    except Exception as e:
        log(f"重新武装失败：{e}", "err")


def _op_reload(cmd, session, bridge, log):
    importlib.reload(P)
    session.policy = P.make_policy("zero", 0.0, 1.5)
    log("已热重载 control.policies，策略回到 zero", "ok")


def _op_quit(cmd, session, bridge, log):
    raise KeyboardInterrupt


_HANDLERS: dict[str, Callable] = {
    "policy": _op_policy,
    "zero": _op_zero,
    "hold": _op_hold,
    "torque": _op_torque,
    "estop": _op_estop,
    "arm": _op_arm,
    "reload": _op_reload,
    "quit": _op_quit,
}

KNOWN_OPS = tuple(_HANDLERS)
