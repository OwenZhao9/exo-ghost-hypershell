"""常驻控制服务：一直连着外骨骼，按命令文件切策略；急停后锁存等待重新武装，不退出。
启动：uv run python -m tools.service --profile table
控制：uv run python -m tools.ctl ...（见 tools/ctl.py）
状态：每秒一行到终端 + data/status.json；事件带时间戳。Ctrl-C 退出（先 DISABLE）。
"""
import argparse, json, math, os, time
from bridge.serial_io import ExoBridge
import importlib
import control.policies as P
from control.safety import SafetyMonitor, PROFILES
from tools.webhub import WebHub, lan_ip

CMD = "data/cmd.json"; STATUS = "data/status.json"

def read_cmd(last_seq):
    try:
        with open(CMD) as f: c = json.load(f)
    except Exception:
        return None
    if c.get("seq", 0) <= last_seq: return None
    return c

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), default="table")
    ap.add_argument("--limit", type=float, default=2.0)
    ap.add_argument("--ramp", type=float, default=3.0, help="力矩斜坡上限 Nm/s（项目规则：默认要慢）")
    ap.add_argument("--port", default=None)
    ap.add_argument("--keepalive", type=float, default=0.0, help="每 N 秒无运动时给左腿一个 1.0 Nm×0.4 s 的脉冲让支架动一下，试图阻止设备闲置待机（0=关）")
    ap.add_argument("--no-web", action="store_true", help="不启动网页仪表盘")
    a = ap.parse_args()
    import queue as _q
    cmdq: "_q.Queue[dict]" = _q.Queue()
    hub = None if a.no_web else WebHub(on_command=cmdq.put)
    prof = PROFILES[a.profile]
    state = {"pol": P.make_policy("zero", 0.0, 1.5), "mon": SafetyMonitor(prof), "seq": 0, "armed": True, "note": "", "pulse_until": 0.0}
    b = ExoBridge(port=a.port, torque_limit=a.limit, ramp_nm_per_s=a.ramp, safety_check=lambda s: state["mon"].trip(s)).open()
    stats = {"n": 0, "work": 0.0, "last_t": None, "scale": 1.0}

    def on_sample(s):
        if state.get("legs_online_at") and time.time() - state["legs_online_at"] < 15.0:
            b.set_torque(0.0, 0.0)
            if hub: hub.push_sample(s, 0.0, 0.0, 0.0)
            return
        if b.legs_offline or not state["armed"]:
            b.set_torque(0.0, 0.0)
            if hub: hub.push_sample(s, 0.0, 0.0, 0.0)
            return
        pol = state["pol"]
        tl0, tr0 = pol.torque(s, 1.0)
        sc = state["mon"].assist_scale(s, tl0, tr0) if pol.name == "assist" else 1.0
        tl, tr = pol.torque(s, sc)
        if s.host_t < state["pulse_until"]:
            tl += 1.0                      # keepalive 脉冲叠加在策略输出上（要大到能克服摩擦让支架动）
        b.set_torque(tl, tr)
        stats["scale"] = sc; stats["n"] += 1
        cl, cr = b.commanded
        if hub: hub.push_sample(s, cl, cr, sc)
        if stats["last_t"] is not None and abs(s.ldps) < 3000 and abs(s.rdps) < 3000:
            dt = s.host_t - stats["last_t"]
            stats["work"] += (cl * math.radians(s.ldps) + cr * math.radians(s.rdps)) * dt
        stats["last_t"] = s.host_t
    b.on_sample(on_sample)

    def log(msg, level="info"):
        print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)
        if hub: hub.push_event(msg, level)
    def on_event(ev):
        if ev == "reconnected":
            state["mon"].notify_reconnect()
        if ev == "legs_online":
            # 实测：腿板上线后 3–10 s 内会有一次 35–40°、1200–1700°/s 的自检快动（右腿为主），
            # 这 15 s 内不判定动态阈值，也不输出任何力矩
            state["mon"] = SafetyMonitor(prof, warmup_s=15.0)
            state["legs_online_at"] = time.time()
            state["last_motion"] = time.time()
            log("腿板上线：15 秒静默期（不出力、不判定），期间支架可能自检快动一次，手不要放在支架旁", "warn")
        if ev.startswith("trip:"):
            state["armed"] = False; state["pol"] = P.make_policy("zero", 0.0, 1.5)
            log(f"!!! 急停锁存：{ev[5:]}   （确认安全后：uv run python -m tools.ctl arm 或页面上点“重新武装”）", "err")
        else:
            log({"legs_offline": "腿部电机板掉线（关节全 0）→ 力矩置零；恢复：机器上短按+长按电源键（不用拔线），等 15 秒静默期",
                 "legs_online": "腿部电机板恢复",
                 "stall": "数据流中断，重连中…", "reconnected": "串口已重连并重新 ENABLE",
                 "stream_slow": "数据流变慢（设备可能正在重启）→ 力矩已清零，观察中…",
                 "device_lost_enable": "设备丢失使能（可能重启过），重新 ENABLE…",
                 "reconnect_failed": "重连失败"}.get(ev, ev))
    b.on_event(on_event)

    def _apply_ramp():
        r = getattr(state["pol"], "ramp_nm_per_s", 3.0)
        if prof.name == "wearing":
            r = min(r, 1.5) * 0.5            # 穿戴：再慢一倍
        b.set_ramp(min(r, a.ramp))
    state["apply_ramp"] = _apply_ramp

    def apply_cmd(c):
        op = c.get("op")
        _dispatch(c, op)
        _apply_ramp()

    def _dispatch(c, op):
        if op == "policy":
            if not state["armed"]:
                log("处于急停锁存，忽略策略命令；先 arm", "warn")
            else:
                state["pol"] = P.make_policy(c["policy"], float(c.get("gain", 0.0)), float(c.get("max", 1.5)))
                log(f"策略 → {state['pol'].name} gain={state['pol'].gain} max={state['pol'].max_torque}", "ok")
        elif op == "zero":
            state["pol"] = P.make_policy("zero", 0.0, 1.5); log("策略 → zero", "ok")
        elif op == "hold":
            if prof.name != "table":
                log("hold（位置保持）只允许在桌面档使用", "err")
            elif not state["armed"]:
                log("处于急停锁存，忽略 hold；先 arm", "warn")
            else:
                if not getattr(state["pol"], "name", "") == "hold":
                    state["pol"] = P.HoldPolicy(kp=float(c.get("kp", 0.08)), kd=float(c.get("kd", 0.006)), ki=float(c.get("ki", 0.04)),
                                              max_torque=float(c.get("max", 1.5)), slew_dps=float(c.get("slew", 15.0)))
                for leg in ("L", "R"):
                    if leg in c:
                        state["pol"].set_target(leg, c[leg])
                log(f"hold 目标 → {state['pol'].status()}  (kp={state['pol'].kp} kd={state['pol'].kd} max={state['pol'].max_torque})", "ok")
        elif op == "estop":
            b.trip("操作员急停")
        elif op == "arm":
            if b.tripped or not state["armed"]:
                state["mon"] = SafetyMonitor(prof); state["pol"] = P.make_policy("zero", 0.0, 1.5)
                try:
                    r = b.rearm(send_torque=True); state["armed"] = True; log(f"重新武装 → {r}，策略 zero", "ok")
                except Exception as e:
                    log(f"重新武装失败：{e}", "err")
            else:
                log("已是武装状态")
        elif op == "torque":
            if prof.name != "table":
                log("恒定力矩只允许在桌面档使用", "err")
            elif not state["armed"]:
                log("处于急停锁存，忽略；先 arm", "warn")
            else:
                state["pol"] = P.TorquePolicy(float(c.get("L", 0.0)), float(c.get("R", 0.0)), float(c.get("seconds", 30.0)), float(c.get("max", 1.5)))
                log(f"恒定力矩 → {state['pol'].status()}（到期自动归零）", "ok")
        elif op == "reload":
            importlib.reload(P); state["pol"] = P.make_policy("zero", 0.0, 1.5)
            log("已热重载 control.policies，策略回到 zero", "ok")
        elif op == "quit":
            raise KeyboardInterrupt

    # 启动时忽略上次遗留的命令文件，避免重放旧策略
    try:
        state["seq"] = json.load(open(CMD)).get("seq", 0)
    except Exception:
        pass
    if hub:
        hub.start()
        print(f"仪表盘：http://localhost:8000  （手机：http://{lan_ip()}:8000）", flush=True)
    print("PING    ->", b.ping()); print("VERSION ->", b.version()); print("ENABLE  ->", b.enable(send_torque=True))
    print(f"安全档 {prof.name}: acc>{prof.acc_trip_g}g gyro>{prof.gyro_trip_dps} tilt>{prof.tilt_trip_deg} 关节>{prof.joint_dps_trip}°/s | 软限幅 ±{a.limit} Nm 斜坡 {a.ramp} Nm/s | 记录 {b.log_path}")
    print(f"{'时间':>8} {'状态':>8} {'策略':>7} {'gain':>5} {'Hz':>4} | {'Ldeg':>6} {'Rdeg':>6} | {'Ldps':>6} {'Rdps':>6} | {'τL':>6} {'τR':>6} | scale  做功J", flush=True)
    last_print = 0.0
    state["last_motion"] = time.time(); pulse_until = 0.0
    try:
        while True:
            time.sleep(0.2)
            # ---- keepalive 脉冲 ----
            s_ = b.latest
            if s_ and (abs(s_.ldps) > 5 or abs(s_.rdps) > 5):
                state["last_motion"] = time.time()
            if a.keepalive > 0 and state["armed"] and not b.legs_offline and b.enabled:
                now_ = time.time()
                if now_ - state["last_motion"] > a.keepalive and now_ > pulse_until + a.keepalive:
                    pulse_until = now_ + 0.4; state["pulse_until"] = pulse_until
                    log("keepalive 脉冲 1.0 Nm × 0.4 s（左腿）")
            c = read_cmd(state["seq"])
            if c:
                state["seq"] = c["seq"]; apply_cmd(c)
            while not cmdq.empty():
                apply_cmd(cmdq.get())
            now = time.time()
            if now - last_print >= 1.0:
                last_print = now; s = b.latest; cl, cr = b.commanded
                st = "TRIPPED" if (b.tripped or not state["armed"]) else ("LEGS_OFF" if b.legs_offline else ("RECONN" if b._reconnecting else "ARMED"))
                if s and s.ldeg == 0.0 and s.rdeg == 0.0 and s.ldps == 0.0 and s.rdps == 0.0 and int(now) % 10 == 0:
                    log("关节数据全 0：腿部电机板掉线 → 机器上短按+长按电源键，等 15 秒静默期即可（不用拔线）")
                if s:
                    line = f"{time.strftime('%H:%M:%S'):>8} {st:>8} {state['pol'].name:>7} {state['pol'].gain:5.2f} {b.stream_hz():4.0f} | {s.ldeg:6.1f} {s.rdeg:6.1f} | {s.ldps:6.0f} {s.rdps:6.0f} | {cl:+6.2f} {cr:+6.2f} | {stats['scale']:.2f}  {stats['work']:+.1f}"
                    print(line, flush=True)
                    st_obj = {"t": now, "state": st, "policy": state["pol"].name, "gain": state["pol"].gain, "max": state["pol"].max_torque,
                              "hz": b.stream_hz(), "work_J": stats["work"], "tripped": b.tripped, "legs_offline": b.legs_offline, "reconnects": b.n_reconnects}
                    if hub: hub.push_status(st_obj)
                    try:
                        json.dump({"t": now, "state": st, "policy": state["pol"].name, "gain": state["pol"].gain, "max": state["pol"].max_torque,
                                   "hz": b.stream_hz(), "ldeg": s.ldeg, "rdeg": s.rdeg, "ldps": s.ldps, "rdps": s.rdps,
                                   "tau_l": cl, "tau_r": cr, "scale": stats["scale"], "work_J": stats["work"], "tripped": b.tripped,
                                   "legs_offline": b.legs_offline, "reconnects": b.n_reconnects, "log": b.log_path}, open(STATUS, "w"))
                    except Exception:
                        pass
    except KeyboardInterrupt:
        print("\nCtrl-C", flush=True)
    finally:
        print("DISABLE ->", b.disable(), flush=True); b.close()

if __name__ == "__main__":
    main()
