"""诊断“持续发 T 一段时间后数据流停止”。
以给定频率持续发 T,0,0，每秒打印 收帧率 / 发送计数 / 输入缓冲 / 错误，检测停流时刻；停流后尝试就地恢复（关串口→重开→ENABLE）。
用法：uv run python -m tools.stall_test --hz 200 --seconds 30
"""
import argparse, time, threading
from bridge.serial_io import ExoBridge

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=int, default=200)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--torque", type=float, default=0.0)
    ap.add_argument("--recover", action="store_true")
    a = ap.parse_args()
    b = ExoBridge(send_hz=a.hz, log_dir=None).open()
    print("PING ->", b.ping(), "| VERSION ->", b.version())
    print("ENABLE ->", b.enable(send_torque=True), f"| 发送 {a.hz} Hz, T={a.torque}")
    b.set_torque(a.torque, 0.0)
    t0 = time.time(); last_n = 0; stall_at = None
    while time.time() - t0 < a.seconds:
        time.sleep(1.0)
        n = b.n_samples; dn = n - last_n; last_n = n
        alive = b._sender.is_alive() if b._sender else False
        iw = b.ser.in_waiting if b.ser and b.ser.is_open else -1
        print(f"t={time.time()-t0:4.1f}s  rx={dn:4d}/s  total={n:6d}  sender={'alive' if alive else 'DEAD'}  in_waiting={iw:5d}  err={b.n_err}  last_err={b.last_err}")
        if dn == 0 and stall_at is None:
            stall_at = time.time() - t0
            print(f"*** 停流，发生在 t≈{stall_at:.1f}s ***")
            if a.recover:
                print("尝试恢复：DISABLE → 关串口 → 重开 → PING → ENABLE")
                try: print("  DISABLE ->", b.disable())
                except Exception as e: print("  DISABLE 异常:", e)
                b._stop.set(); 
                try: b.ser.close()
                except Exception: pass
                time.sleep(0.5)
                b2 = ExoBridge(send_hz=a.hz, log_dir=None).open()
                try:
                    print("  PING ->", b2.ping()); print("  ENABLE ->", b2.enable(send_torque=True))
                    b2.set_torque(a.torque, 0.0); b = b2; last_n = 0; stall_at = None
                except Exception as e:
                    print("  恢复失败:", e); break
    print("DISABLE ->", b.disable()); b.close()

if __name__ == "__main__":
    main()
