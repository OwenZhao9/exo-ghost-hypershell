"""第 1 步：确认电脑能跟外骨骼说上话。
用法：uv run python -m tools.ping [--port /dev/cu.usbmodemXXXX]
"""
import argparse, sys
from bridge.serial_io import ExoBridge, find_port

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    a = ap.parse_args()
    port = a.port or find_port()
    if not port:
        print("没找到串口（/dev/cu.usbserial* 或 usbmodem*）。检查：外骨骼开机了吗？USB 线能传数据吗？"); sys.exit(1)
    print(f"串口：{port}")
    b = ExoBridge(port=port, log_dir=None).open()
    try:
        print("PING    ->", b.ping())
        print("VERSION ->", b.version())
        print("OK：连通。下一步 uv run python -m tools.monitor")
    finally:
        b.close()

if __name__ == "__main__":
    main()
