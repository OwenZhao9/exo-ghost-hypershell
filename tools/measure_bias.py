"""测量「设备上电基础力矩 + 机械摩擦」：极慢加力，找支架刚开始动的临界力矩。

原理：支架静止时，外力（重力）被「设备基础力矩 + 静摩擦」托住。
  - 向下极慢加力，临界值 D = 摩擦 + 基础力矩(向上为正时抵抗向下)
  - 向上极慢加力，临界值 U = 摩擦 − 基础力矩
  → 基础力矩 ≈ (D − U) / 2，摩擦 ≈ (D + U) / 2
按项目规则：斜坡 0.1 Nm/s（默认），一检测到运动立即归零。全程桌面，勿穿戴。

用法：uv run python -m tools.measure_bias            # 左右腿各测上下两个方向
      uv run python -m tools.measure_bias --leg R --rate 0.05 --max 2.0
"""
import argparse, time
from bridge.serial_io import ExoBridge
from control.policies import UP_SIGN

MOVE_DPS = 6.0          # 判定"开始动"的角速度阈值
MOVE_DEG = 2.0          # 或角度偏离起点这么多

def ramp_until_move(b, leg, direction, rate, tau_max, settle=1.0):
    """direction=+1 向上，-1 向下。返回 (临界力矩, 是否到上限仍未动, 起始角度)"""
    sign = UP_SIGN[leg] * direction
    time.sleep(settle)
    s0 = b.latest
    if s0 is None: raise RuntimeError("没有数据")
    a0 = s0.ldeg if leg == "L" else s0.rdeg
    t0 = time.perf_counter(); tau = 0.0
    hit = None
    while tau < tau_max:
        tau = min(tau_max, (time.perf_counter() - t0) * rate)
        b.set_torque(sign * tau if leg == "L" else 0.0, sign * tau if leg == "R" else 0.0)
        time.sleep(0.02)
        s = b.latest
        if s is None: continue
        a = s.ldeg if leg == "L" else s.rdeg
        w = s.ldps if leg == "L" else s.rdps
        if abs(w) < 3000 and (abs(w) > MOVE_DPS or abs(a - a0) > MOVE_DEG):
            hit = tau; break
    b.set_torque(0.0, 0.0)
    time.sleep(0.8)
    return hit, (hit is None), a0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", choices=["L", "R", "both"], default="both")
    ap.add_argument("--rate", type=float, default=0.1, help="加力速度 Nm/s（项目规则：要慢）")
    ap.add_argument("--max", type=float, default=2.0, help="最大力矩 Nm")
    ap.add_argument("--port", default=None)
    a = ap.parse_args()

    b = ExoBridge(port=a.port, torque_limit=a.max, ramp_nm_per_s=max(a.rate * 2, 0.3), log_dir="data").open()
    try:
        print("PING ->", b.ping(), "| VERSION ->", b.version())
        print("ENABLE ->", b.enable(send_torque=True))
        print(f"加力速度 {a.rate} Nm/s，上限 {a.max} Nm，检测到运动立即归零\n")
        legs = ["L", "R"] if a.leg == "both" else [a.leg]
        res = {}
        for leg in legs:
            out = {}
            for name, d in (("向下", -1), ("向上", +1)):
                print(f"  {leg} 腿 {name} 慢慢加力…", end="", flush=True)
                hit, maxed, a0 = ramp_until_move(b, leg, d, a.rate, a.max)
                out[name] = hit
                print(f" 起始 {a0:7.2f}°  →  " + (f"{hit:.2f} Nm 时开始动" if hit else f"到 {a.max} Nm 仍未动"))
            res[leg] = out
        print()
        for leg, o in res.items():
            D, U = o["向下"], o["向上"]
            if D and U:
                print(f"{leg} 腿：向下临界 {D:.2f} Nm，向上临界 {U:.2f} Nm  →  上电基础力矩 ≈ {(D-U)/2:+.2f} Nm（正=向上），静摩擦 ≈ {(D+U)/2:.2f} Nm")
            else:
                print(f"{leg} 腿：数据不全（向下 {D}，向上 {U}），可能被限位挡住或力矩上限不够")
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        print("DISABLE ->", b.disable()); print("数据：", b.log_path); b.close()

if __name__ == "__main__":
    main()
