"""快速探针：串口一出现就立刻打开，发 PING/VERSION，把 3 秒内收到的所有东西原样打印。
用于诊断"设备出现几秒就掉线"的情况。用法：uv run python -m tools.probe [--wait 600]
"""
import argparse, glob, sys, time
import serial

def wait_port(timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for g in ("/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.usbmodem*"):
            c = sorted(glob.glob(g))
            if c: return c[0]
        time.sleep(0.05)
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--wait", type=float, default=600); a = ap.parse_args()
    print("等待串口出现…", flush=True)
    port = wait_port(a.wait)
    if not port: print("超时，没出现"); sys.exit(1)
    t_seen = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] 出现 {port}", flush=True)
    try:
        s = serial.Serial(port, 3_000_000, timeout=0.05)
    except Exception as e:
        print(f"打开失败：{e}"); sys.exit(2)
    print(f"打开成功 (+{(time.time()-t_seen)*1000:.0f} ms)", flush=True)
    t0 = time.time(); last_rx = None; n = 0
    try:
        for cmd in ("PING", "VERSION", "PING"):
            s.write((cmd + "\n").encode()); print(f"  -> {cmd}", flush=True)
            t1 = time.time()
            while time.time() - t1 < 0.6:
                line = s.readline()
                if line:
                    n += 1; last_rx = time.time()
                    print(f"  <- (+{(time.time()-t0)*1000:5.0f} ms) {line!r}", flush=True)
        print("  继续监听 4 秒…", flush=True)
        t1 = time.time()
        while time.time() - t1 < 4.0:
            line = s.readline()
            if line:
                n += 1; last_rx = time.time()
                if n <= 15: print(f"  <- (+{(time.time()-t0)*1000:5.0f} ms) {line!r}", flush=True)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 串口异常 (+{(time.time()-t_seen)*1000:.0f} ms 后)：{e}", flush=True)
    finally:
        try: s.close()
        except Exception: pass
    print(f"共收到 {n} 行；最后一行在 +{((last_rx or t0)-t0)*1000:.0f} ms；串口节点现在{'还在' if glob.glob(port) else '已消失'}")

if __name__ == "__main__":
    main()
