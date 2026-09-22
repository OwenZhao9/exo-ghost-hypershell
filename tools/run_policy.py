"""在设备上跑一种策略，带安全监视器。
  uv run python -m tools.run_policy --policy resist --gain 0.5 --seconds 600            # 桌面（profile=table）
  uv run python -m tools.run_policy --policy assist --gain 0.2 --max 0.8 --seconds 300   # 桌面助力，带速度/角度/能量渐弱
  uv run python -m tools.run_policy --policy resist --gain 0.3 --profile wearing        # 穿戴：加速度/陀螺/倾角急停 + 10 分钟上限
急停路径：Ctrl-C / 关终端 / 拔 USB（固件 115 ms 清零）/ 任一安全阈值触发（锁存，需重新启动程序）。
"""
import argparse, math, time
from bridge.serial_io import ExoBridge
from control.policies import make_policy
from control.safety import SafetyMonitor, PROFILES

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="resist")
    ap.add_argument("--gain", type=float, default=0.5, help="Nm per rad/s")
    ap.add_argument("--max", type=float, default=1.5, help="策略力矩上限 Nm")
    ap.add_argument("--limit", type=float, default=2.0, help="bridge 软限幅 Nm")
    ap.add_argument("--ramp", type=float, default=12.0, help="力矩斜坡 Nm/s")
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--port", default=None)
    ap.add_argument("--profile", choices=list(PROFILES), default="table")
    ap.add_argument("--inject-trip-after", type=float, default=None, help="测试用：N 秒后软件注入一次急停，验证 trip→DISABLE 链路")
    a = ap.parse_args()

    prof = PROFILES[a.profile]
    pol = make_policy(a.policy, a.gain, a.max)
    mon = SafetyMonitor(prof)
    b = ExoBridge(port=a.port, torque_limit=a.limit, ramp_nm_per_s=a.ramp, safety_check=mon.trip).open()
    stats = {"n": 0, "maxL": 0.0, "maxR": 0.0, "workL": 0.0, "workR": 0.0, "last_t": None, "min_scale": 1.0}

    def on_sample(s):
        if b.legs_offline:
            b.set_torque(0.0, 0.0); return
        # 先算一遍名义力矩，用于能量预算；再按 scale 得到实际力矩
        tl0, tr0 = pol.torque(s, 1.0)
        sc = mon.assist_scale(s, tl0, tr0) if pol.name == "assist" else 1.0
        tl, tr = pol.torque(s, sc)
        b.set_torque(tl, tr)
        cl, cr = b.commanded
        stats["n"] += 1; stats["min_scale"] = min(stats["min_scale"], sc)
        stats["maxL"] = max(stats["maxL"], abs(cl)); stats["maxR"] = max(stats["maxR"], abs(cr))
        if stats["last_t"] is not None and abs(s.ldps) < 3000 and abs(s.rdps) < 3000:
            dt = s.host_t - stats["last_t"]
            stats["workL"] += cl * math.radians(s.ldps) * dt
            stats["workR"] += cr * math.radians(s.rdps) * dt
        stats["last_t"] = s.host_t
    b.on_sample(on_sample)

    def on_event(ev):
        msg = {"legs_offline": "腿部电机板掉线（关节数据全 0）→ 力矩置零，需要给外骨骼断电重启",
               "legs_online": "腿部电机板恢复",
               "stall": "数据流中断，正在重连…",
               "reconnected": "串口已重连并重新 ENABLE",
               "device_lost_enable": "设备丢失使能状态（可能重启过），正在重新 ENABLE…",
               "reconnect_failed": "重连失败，已急停"}.get(ev, ev)
        if ev.startswith("trip:"): msg = "急停：" + ev[5:]
        print(f"  [事件 {time.strftime('%H:%M:%S')}] {msg}", flush=True)
    b.on_event(on_event)

    try:
        print("PING    ->", b.ping()); print("VERSION ->", b.version())
        print("ENABLE  ->", b.enable(send_torque=True))
        print(f"策略 {pol.name} gain={pol.gain} max={pol.max_torque} Nm | 软限幅 ±{b.torque_limit} Nm 斜坡 {a.ramp} Nm/s | 安全档 {prof.name}: "
              f"acc>{prof.acc_trip_g}g gyro>{prof.gyro_trip_dps}°/s tilt>{prof.tilt_trip_deg} 关节>{prof.joint_dps_trip}°/s 流<{prof.min_stream_hz}Hz 时长<{prof.max_session_s}s", flush=True)
        print(f"记录 {b.log_path}\n{'t':>6} {'Hz':>4} | {'Ldeg':>6} {'Rdeg':>6} | {'Ldps':>6} {'Rdps':>6} | {'τL':>6} {'τR':>6} | scale", flush=True)
        t0 = time.time()
        injected = False
        while time.time() - t0 < a.seconds and not b.tripped:
            time.sleep(0.5)
            if a.inject_trip_after is not None and not injected and time.time() - t0 >= a.inject_trip_after:
                injected = True; b.trip("软件注入测试")
            s = b.latest; cl, cr = b.commanded
            if s: print(f"{time.time()-t0:6.1f} {b.stream_hz():4.0f} | {s.ldeg:6.1f} {s.rdeg:6.1f} | {s.ldps:6.0f} {s.rdps:6.0f} | {cl:+6.2f} {cr:+6.2f} | {mon.last_scale:.2f}", flush=True)
    except KeyboardInterrupt:
        print("\nCtrl-C → 力矩清零", flush=True)
    finally:
        print("DISABLE ->", b.disable(), flush=True)
        print(f"帧 {stats['n']}  |τ|max L={stats['maxL']:.2f} R={stats['maxR']:.2f} Nm  设备做功 L={stats['workL']:+.2f} J R={stats['workR']:+.2f} J  "
              f"assist 最小 scale={stats['min_scale']:.2f}  重连 {b.n_reconnects} 次  last_err={b.last_err}", flush=True)
        if b.tripped: print("急停原因：", b.tripped, flush=True)
        print("数据：", b.log_path, flush=True)
        b.close()

if __name__ == "__main__":
    main()
