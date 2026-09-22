"""第 3 步：让某条腿持续用一个固定的劲，看它往哪边动、角度数字怎么变（测方向 / 测看门狗）。
用法：
  uv run python -m tools.hold --left 1.0 --right 0 --seconds 1
  uv run python -m tools.hold --left 0 --right 1.0 --seconds 1
  uv run python -m tools.hold --left 0.5 --right 0 --seconds 1 --test-watchdog   # 到时后突然停止续发，观察是否自动松劲
安全：默认软限幅 ±2.0 Nm（--limit 可改，最高 7.5）；斜坡 0.2 Nm / 50 ms；先在桌面上测，不要穿在人身上跑这个。
"""
import argparse, time
from bridge.serial_io import ExoBridge, FIRMWARE_LIMIT_NM

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", type=float, default=0.0)
    ap.add_argument("--right", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--limit", type=float, default=2.0)
    ap.add_argument("--port", default=None)
    ap.add_argument("--test-watchdog", action="store_true")
    a = ap.parse_args()
    lim = min(abs(a.limit), FIRMWARE_LIMIT_NM)
    if abs(a.left) > lim or abs(a.right) > lim:
        raise SystemExit(f"力矩超过软限幅 ±{lim} Nm；确认安全后用 --limit 提高")

    b = ExoBridge(port=a.port, torque_limit=lim).open()
    try:
        print("PING    ->", b.ping())
        print("VERSION ->", b.version())
        print("ENABLE  ->", b.enable(send_torque=True), "（200 Hz 续发已启动，当前 T,0,0）")
        time.sleep(0.5)
        s0 = b.latest
        print(f"起始角度  L={s0.ldeg:7.2f}  R={s0.rdeg:7.2f}" if s0 else "还没收到数据")
        print(f"\n>>> 目标 T,{a.left},{a.right}，保持 {a.seconds}s（斜坡上升）")
        b.set_torque(a.left, a.right)
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            time.sleep(0.25)
            s = b.latest; cl, cr = b.commanded
            if s:
                print(f"  t={time.time()-t0:4.2f}s  cmd=({cl:+.2f},{cr:+.2f})  Ldeg={s.ldeg:7.2f} Rdeg={s.rdeg:7.2f}  Ldps={s.ldps:7.1f} Rdps={s.rdps:7.1f}  Hz={b.stream_hz():.0f}")
        if a.test_watchdog:
            print("\n>>> 看门狗测试：突然停止续发（故意不发 T,0,0），设备应在 100 ms 内自行松劲。观察支架是否松开：")
            t_stop = b.stop_sender(zero_on_exit=False)
            for _ in range(8):
                time.sleep(0.05)
                s = b.latest
                if s:
                    print(f"  +{(time.perf_counter()-t_stop)*1000:5.0f} ms  Ldps={s.ldps:7.1f} Rdps={s.rdps:7.1f}  Ldeg={s.ldeg:7.2f} Rdeg={s.rdeg:7.2f}")
        else:
            print("\n>>> 目标归零（斜坡下降）")
            b.set_torque(0.0, 0.0)
            time.sleep(max(0.6, (abs(a.left) + abs(a.right)) / 4.0 + 0.2))
        s1 = b.latest
        if s0 and s1:
            print(f"\n角度变化  ΔL={s1.ldeg - s0.ldeg:+7.2f}°  ΔR={s1.rdeg - s0.rdeg:+7.2f}°   ← 记下正力矩对应的方向")
    except KeyboardInterrupt:
        pass
    finally:
        print("DISABLE ->", b.disable())
        print(f"数据：{b.log_path}")
        b.close()

if __name__ == "__main__":
    main()
