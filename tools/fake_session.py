"""生成一段假的步态数据 CSV（正弦髋角，~1 Hz 步频），用于没有硬件时测试回放/控制器。
用法：uv run python -m tools.fake_session [--seconds 10] [--out data/fake.csv]
"""
import argparse, csv, math, os
from dataclasses import fields
from bridge.serial_io import Sample

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--out", default="data/fake.csv")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    f_step = 0.9  # 步频 Hz（每条腿）
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow([x.name for x in fields(Sample)])
        n = int(a.seconds * 200)
        for i in range(n):
            t = i / 200.0
            l = 25 * math.sin(2 * math.pi * f_step * t)
            r = 25 * math.sin(2 * math.pi * f_step * t + math.pi)
            ld = 25 * 2 * math.pi * f_step * math.cos(2 * math.pi * f_step * t)
            rd = 25 * 2 * math.pi * f_step * math.cos(2 * math.pi * f_step * t + math.pi)
            w.writerow([t, t * 1000, 2 * math.sin(2 * math.pi * 2 * f_step * t), 0.5, 0.0,
                        0, 0, 0, 0.05 * math.sin(2 * math.pi * 2 * f_step * t), 0, 1.0,
                        101.325 - 0.0001 * t, l, r, ld, rd, 0, 0])
    print("写入", a.out, n, "帧")

if __name__ == "__main__":
    main()
