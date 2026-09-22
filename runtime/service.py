"""常驻控制服务的主循环。

职责只有三件：把 bridge / 策略 / 安全监视器接起来；每秒打一行状态；
把命令交给 `runtime.commands`。具体怎么算力矩在 `control/`，
怎么跟设备说话在 `bridge/`，怎么翻译事件在 `runtime/events.py`。
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import time
from typing import Optional

from bridge.exo import ExoBridge
from bridge.protocol import DPS_SATURATION
from control.safety import PROFILES
from runtime import commands, events, status
from runtime.session import Session
from tools.webhub import WebHub, lan_ip

CMD_FILE = "data/cmd.json"
STATUS_FILE = "data/status.json"
KEEPALIVE_PULSE_NM = 1.0         # 保活脉冲要大到能克服静摩擦（实测约 0.5 Nm 才动）
KEEPALIVE_PULSE_S = 0.4


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="外骨骼常驻控制服务")
    ap.add_argument("--profile", choices=list(PROFILES), default="table")
    ap.add_argument("--limit", type=float, default=2.0, help="软限幅 Nm")
    ap.add_argument("--ramp", type=float, default=3.0,
                    help="力矩斜坡上限 Nm/s（项目规则：默认要慢）")
    ap.add_argument("--port", default=None)
    ap.add_argument("--keepalive", type=float, default=0.0,
                    help=f"每 N 秒无运动时给左腿一个 {KEEPALIVE_PULSE_NM} Nm×"
                         f"{KEEPALIVE_PULSE_S} s 的脉冲，试图阻止设备闲置待机（0=关）")
    ap.add_argument("--no-web", action="store_true", help="不启动网页仪表盘")
    ap.add_argument("--body", choices=["auto", "real", "sim"], default="auto",
                    help="用哪具身体：real=真外骨骼，sim=数字义体，auto=找不到真机就用义体")
    return ap


def make_bridge(a, session):
    """按 --body 选一具身体。两者接口一致，服务本身不关心用的是哪个。"""
    from bridge.ports import find_port
    safety = lambda s: session.monitor.trip(s)      # noqa: E731
    want = a.body
    if want == "auto":
        want = "real" if find_port() else "sim"
    if want == "sim":
        from bridge.sim import SimBridge
        print("身体：数字义体（sim）—— 参数来自真机录制的辨识结果", flush=True)
        return SimBridge(torque_limit=a.limit, ramp_nm_per_s=a.ramp, safety_check=safety).open()
    print("身体：真外骨骼（real）", flush=True)
    return ExoBridge(port=a.port, torque_limit=a.limit, ramp_nm_per_s=a.ramp,
                     safety_check=safety).open()


def read_cmd_file(last_seq: int) -> Optional[dict]:
    """读命令文件；序号没涨就当没有新命令。"""
    try:
        with open(CMD_FILE) as f:
            c = json.load(f)
    except Exception:
        return None
    return c if c.get("seq", 0) > last_seq else None


def main(argv: Optional[list[str]] = None) -> None:
    a = build_parser().parse_args(argv)
    prof = PROFILES[a.profile]
    session = Session(profile=prof, ramp_cap_nm_s=a.ramp)

    cmdq: "queue.Queue[dict]" = queue.Queue()
    hub = None if a.no_web else WebHub(on_command=cmdq.put)

    bridge = make_bridge(a, session)
    stats = {"n": 0, "work": 0.0, "last_t": None, "scale": 1.0}

    def log(msg: str, level: str = "info") -> None:
        print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)
        if hub:
            hub.push_event(msg, level)

    # ---------- 逐帧回调（跑在串口读线程里，要快） ----------
    def on_sample(s) -> None:
        quiet = session.in_quiet_period(time.time(), events.LEGS_ONLINE_QUIET_S)
        if quiet or bridge.legs_offline or not session.armed:
            bridge.set_torque(0.0, 0.0)
            if hub:
                hub.push_sample(s, 0.0, 0.0, 0.0)
            return
        pol = session.policy
        tl0, tr0 = pol.torque(s, 1.0)
        sc = session.monitor.assist_scale(s, tl0, tr0) if pol.name == "assist" else 1.0
        tl, tr = pol.torque(s, sc)
        if s.host_t < session.pulse_until:
            tl += KEEPALIVE_PULSE_NM        # 保活脉冲叠加在策略输出上
        bridge.set_torque(tl, tr)
        stats["scale"] = sc
        stats["n"] += 1
        cl, cr = bridge.commanded
        if hub:
            hub.push_sample(s, cl, cr, sc)
        if stats["last_t"] is not None and abs(s.ldps) < DPS_SATURATION and abs(s.rdps) < DPS_SATURATION:
            dt = s.host_t - stats["last_t"]
            stats["work"] += (cl * math.radians(s.ldps) + cr * math.radians(s.rdps)) * dt
        stats["last_t"] = s.host_t

    bridge.on_sample(on_sample)

    # ---------- 设备事件 ----------
    def on_event(ev: str) -> None:
        if ev == "reconnected":
            session.monitor.notify_reconnect()
        if ev == "legs_online":
            # 实测：腿板上线后 3–10 s 内会有一次 35–40°、1200–1700 °/s 的自检快动
            from control.safety import SafetyMonitor
            session.monitor = SafetyMonitor(prof, warmup_s=events.LEGS_ONLINE_QUIET_S)
            session.legs_online_at = time.time()
            session.last_motion = time.time()
            log(events.LEGS_ONLINE_HINT, "warn")
            return
        if ev.startswith("trip:"):
            session.armed = False
            import control.policies as P
            session.policy = P.make_policy("zero", 0.0, 1.5)
        msg, level = events.describe(ev)
        log(msg, level)

    bridge.on_event(on_event)

    # 启动时忽略上次遗留的命令文件，避免重放旧策略
    try:
        session.seq = json.load(open(CMD_FILE)).get("seq", 0)
    except Exception:
        pass

    if hub:
        hub.start()
        print(f"仪表盘：http://localhost:8000  （手机：http://{lan_ip()}:8000）", flush=True)
    print("PING    ->", bridge.ping())
    print("VERSION ->", bridge.version())
    print("ENABLE  ->", bridge.enable(send_torque=True))
    print(f"安全档 {prof.name}: acc>{prof.acc_trip_g}g gyro>{prof.gyro_trip_dps} "
          f"tilt>{prof.tilt_trip_deg} 关节>{prof.joint_dps_trip}°/s | "
          f"软限幅 ±{a.limit} Nm 斜坡 {a.ramp} Nm/s | 记录 {bridge.log_path}")
    print(status.HEADER, flush=True)

    last_print = 0.0
    try:
        while True:
            time.sleep(0.2)
            now = time.time()

            # 保活脉冲
            s_ = bridge.latest
            if s_ and (abs(s_.ldps) > 5 or abs(s_.rdps) > 5):
                session.last_motion = now
            if (a.keepalive > 0 and session.armed and not bridge.legs_offline
                    and bridge.enabled
                    and now - session.last_motion > a.keepalive
                    and now > session.pulse_until + a.keepalive):
                session.pulse_until = now + KEEPALIVE_PULSE_S
                log(f"keepalive 脉冲 {KEEPALIVE_PULSE_NM} Nm × {KEEPALIVE_PULSE_S} s（左腿）")

            # 命令：文件与网页两条来源，同一个分发器
            c = read_cmd_file(session.seq)
            if c:
                session.seq = c["seq"]
                commands.apply(c, session=session, bridge=bridge, log=log)
            while not cmdq.empty():
                commands.apply(cmdq.get(), session=session, bridge=bridge, log=log)

            # 每秒一行状态
            if now - last_print >= 1.0:
                last_print = now
                s = bridge.latest
                cl, cr = bridge.commanded
                st = status.device_state(tripped=bridge.tripped, armed=session.armed,
                                         legs_offline=bridge.legs_offline,
                                         reconnecting=bridge._reconnecting)
                if not s:
                    continue
                print(status.console_line(
                    state=st, policy=session.policy.name, gain=session.policy.gain,
                    hz=bridge.stream_hz(), ldeg=s.ldeg, rdeg=s.rdeg, ldps=s.ldps, rdps=s.rdps,
                    tau_l=cl, tau_r=cr, scale=stats["scale"], work_J=stats["work"]), flush=True)
                base = status.snapshot(
                    t=now, state=st, policy=session.policy.name, gain=session.policy.gain,
                    max_torque=session.policy.max_torque, hz=bridge.stream_hz(),
                    work_J=stats["work"], tripped=bridge.tripped,
                    legs_offline=bridge.legs_offline, reconnects=bridge.n_reconnects)
                if hub:
                    hub.push_status(base)
                status.write_status_file(STATUS_FILE, status.full_snapshot(
                    base, ldeg=s.ldeg, rdeg=s.rdeg, ldps=s.ldps, rdps=s.rdps,
                    tau_l=cl, tau_r=cr, scale=stats["scale"], log=bridge.log_path))
    except KeyboardInterrupt:
        print("\nCtrl-C", flush=True)
    finally:
        print("DISABLE ->", bridge.disable(), flush=True)
        bridge.close()


if __name__ == "__main__":
    main()
