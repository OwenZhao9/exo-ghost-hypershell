"""第 2 步：只读模式。ENABLE 后看 200 Hz 数据流，不发任何力矩。
用法：uv run python -m tools.monitor [--seconds 30] [--port ...] [--raw]
  --raw   前 5 行原始数据打印出来（排查格式用）
Ctrl-C 结束，退出时自动 DISABLE。数据存到 data/session_*.csv
"""
import argparse, time
from bridge.serial_io import ExoBridge

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()

    b = ExoBridge(port=a.port).open()
    if a.raw:
        shown = [0]
        def show(s):
            if shown[0] < 5:
                shown[0] += 1; print("   RAW:", s)
        b.on_sample(show)
    try:
        print("PING    ->", b.ping())
        print("VERSION ->", b.version())
        print("ENABLE  ->", b.enable(send_torque=False), "（只读，不发力矩）")
        print(f"记录到 {b.log_path}\n")
        print(f"{'t':>5} {'Hz':>5} | {'Ldeg':>7} {'Rdeg':>7} | {'Ldps':>7} {'Rdps':>7} | {'pitch':>6} {'roll':>6} {'yaw':>6} | {'kPa':>8} | bad err")
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            time.sleep(0.5)
            s = b.latest
            if s is None:
                print(f"{time.time()-t0:5.1f}  ---  还没收到 S: 帧（ENABLE 后应立刻有）"); continue
            print(f"{time.time()-t0:5.1f} {b.stream_hz():5.0f} | {s.ldeg:7.2f} {s.rdeg:7.2f} | {s.ldps:7.1f} {s.rdps:7.1f} | "
                  f"{s.pitch:6.1f} {s.roll:6.1f} {s.yaw:6.1f} | {s.kpa:8.3f} | {b.n_bad_lines:3d} {b.n_err:3d}")
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDISABLE ->", b.disable())
        print(f"共 {b.n_samples} 帧，坏行 {b.n_bad_lines}，ERR {b.n_err}，最后错误：{b.last_err}")
        print(f"文件：{b.log_path}")
        b.close()

if __name__ == "__main__":
    main()
