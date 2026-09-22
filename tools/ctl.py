"""给常驻服务发命令（写 data/cmd.json）。
  uv run python -m tools.ctl policy resist --gain 0.5 --max 1.5
  uv run python -m tools.ctl policy assist --gain 0.2 --max 0.8
  uv run python -m tools.ctl zero        # 松劲但保持连接
  uv run python -m tools.ctl estop       # 急停（锁存）
  uv run python -m tools.ctl arm         # 急停后重新武装（回到 zero）
  uv run python -m tools.ctl status      # 看最近一秒状态
  uv run python -m tools.ctl recall "腿板掉线"        # 让 Ghost 去经验库里查
  uv run python -m tools.ctl fault legs_offline       # 给数字义体注入一次故障
  uv run python -m tools.ctl quit
"""
import argparse, json, os, time
CMD = "data/cmd.json"; STATUS = "data/status.json"

def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="op", required=True)
    p = sub.add_parser("policy"); p.add_argument("policy", choices=["zero", "resist", "assist"]); p.add_argument("--gain", type=float, default=0.5); p.add_argument("--max", type=float, default=1.5)
    h = sub.add_parser("hold", help="位置保持（仅桌面）：--left/--right 目标角度°，free 表示放开")
    h.add_argument("--left", default=None); h.add_argument("--right", default=None)
    h.add_argument("--kp", type=float, default=0.08); h.add_argument("--kd", type=float, default=0.006); h.add_argument("--ki", type=float, default=0.04)
    h.add_argument("--max", type=float, default=1.5); h.add_argument("--slew", type=float, default=15.0, help="目标角变化速度 °/s（默认 15，慢）")
    tq = sub.add_parser("torque", help="恒定力矩（仅桌面）：--left/--right Nm，--seconds 到期自动归零")
    tq.add_argument("--left", type=float, default=0.0); tq.add_argument("--right", type=float, default=0.0)
    tq.add_argument("--seconds", type=float, default=30.0); tq.add_argument("--max", type=float, default=1.5)
    up = sub.add_parser("up", help="两腿同时向上（左负右正，现场确认的方向）：up <Nm> [--seconds N]")
    up.add_argument("nm", type=float); up.add_argument("--seconds", type=float, default=30.0)
    dn = sub.add_parser("down", help="两腿同时向下（左正右负）：down <Nm> [--seconds N]")
    dn.add_argument("nm", type=float); dn.add_argument("--seconds", type=float, default=30.0)
    from bridge.faults import FAULT_KINDS
    ft = sub.add_parser("fault", help="给数字义体注入故障（仅 --body sim）：" +
                        "；".join(f"{k}={v.split('：')[0]}" for k, v in FAULT_KINDS.items()))
    ft.add_argument("kind", choices=sorted(FAULT_KINDS))
    ft.add_argument("--delay", type=float, default=0.0, help="几秒后开始")
    ft.add_argument("--seconds", type=float, default=6.0, help="持续多久后自动恢复")
    from bridge.wearer import GAITS
    gt = sub.add_parser("gait", help="给数字义体挂一个穿戴者按步态走路（仅 --body sim）：" +
                        "；".join(g.note for g in GAITS.values()))
    gt.add_argument("name", nargs="?", default=None, choices=[*sorted(GAITS), "off"])
    rc = sub.add_parser("recall", help="让 Ghost 去经验库里查一次，结果出现在事件栏")
    rc.add_argument("query"); rc.add_argument("-k", type=int, default=3)
    for n in ("zero", "estop", "arm", "quit", "status", "reload"): sub.add_parser(n)
    a = ap.parse_args()
    if a.op == "status":
        try:
            st = json.load(open(STATUS)); age = time.time() - st["t"]
            print(f"({age:.0f}s 前) {st['state']} {st['policy']} gain={st['gain']} {st['hz']:.0f}Hz  L={st['ldeg']:.1f}° R={st['rdeg']:.1f}°  ω=({st['ldps']:.0f},{st['rdps']:.0f})  τ=({st['tau_l']:+.2f},{st['tau_r']:+.2f})  scale={st['scale']:.2f}  做功 {st['work_J']:+.1f} J  tripped={st['tripped']}  legs_offline={st['legs_offline']}")
        except Exception as e:
            print("没有状态文件（服务没在跑？）", e)
        return
    seq = int(time.time() * 1000)
    cmd = {"seq": seq, "op": a.op}
    if a.op == "policy": cmd.update(policy=a.policy, gain=a.gain, max=a.max)
    if a.op == "torque":
        cmd.update(L=a.left, R=a.right, seconds=a.seconds, max=a.max)
    if a.op == "up":
        cmd.update(op="torque", L=-abs(a.nm), R=+abs(a.nm), seconds=a.seconds, max=1.5)
    if a.op == "down":
        cmd.update(op="torque", L=+abs(a.nm), R=-abs(a.nm), seconds=a.seconds, max=1.5)
    if a.op == "fault": cmd.update(kind=a.kind, delay=a.delay, seconds=a.seconds)
    if a.op == "recall": cmd.update(query=a.query, k=a.k)
    if a.op == "gait": cmd.update(name=None if a.name in (None, "off") else a.name)
    if a.op == "hold":
        cmd.update(kp=a.kp, kd=a.kd, ki=a.ki, max=a.max, slew=a.slew)
        for leg, v in (("L", a.left), ("R", a.right)):
            if v is not None:
                cmd[leg] = None if v.lower() == "free" else float(v)
    os.makedirs("data", exist_ok=True)
    tmp = CMD + ".tmp"; json.dump(cmd, open(tmp, "w")); os.replace(tmp, CMD)
    print("已发送:", cmd)

if __name__ == "__main__":
    main()
