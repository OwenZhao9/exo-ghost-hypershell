"""常驻控制服务的主循环。

职责只有三件：把 bridge / 策略 / 安全监视器接起来；每秒打一行状态；
把命令交给 `runtime.commands`。具体怎么算力矩在 `control/`，
怎么跟设备说话在 `bridge/`，怎么翻译事件在 `runtime/events.py`。
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import queue
import time
from typing import Optional

import control.policies as P
from bridge.exo import ExoBridge
from bridge.protocol import DPS_SATURATION
from control.safety import PROFILES
from runtime import commands, events, status
from runtime.journal import Journal
from runtime.session import Session
from tools.webhub import WebHub, lan_ip

CMD_FILE = "data/cmd.json"
STATUS_FILE = "data/status.json"
EVOMAP_GATEWAY_BASE_URL = "https://api.evomap.ai/v1"
EVOMAP_DEFAULT_MODEL = "evomap-gemini-3.1-pro-preview"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="外骨骼常驻控制服务")
    ap.add_argument("--profile", choices=list(PROFILES), default="table")
    ap.add_argument("--limit", type=float, default=2.0, help="软限幅 Nm")
    ap.add_argument("--ramp", type=float, default=3.0,
                    help="力矩斜坡上限 Nm/s（项目规则：默认要慢）")
    ap.add_argument("--port", default=None)
    ap.add_argument("--keepalive", type=float, default=0.0,
                    help="旧版保活力矩脉冲已停用；只能设为 0")
    ap.add_argument("--no-web", action="store_true", help="不启动网页仪表盘")
    ap.add_argument("--http-port", type=int, default=8000, help="网页端口")
    ap.add_argument("--ws-port", type=int, default=8765, help="遥测 WebSocket 端口")
    ap.add_argument("--state-dir", default="data", help="命令、状态和会话记录目录")
    ap.add_argument("--no-memory", action="store_true",
                    help="不加载经验库（默认加载 data/genes.db，遇到设备异常会自动回忆解法）")
    ap.add_argument("--memory-db", default="data/genes.db", help="经验库路径")
    ap.add_argument("--no-decide", action="store_true", help="不启用直觉层（Ghost 不再给策略建议）")
    ap.add_argument("--autopilot", action="store_true",
                    help="让 Ghost 真的下发它的决定（默认只建议不下发）")
    ap.add_argument("--min-confidence", type=float, default=0.55,
                    help="置信度门控阈值：低于它就保持原策略不动")
    ap.add_argument("--decide-period", type=float, default=2.0, help="每隔几秒决策一次")
    ap.add_argument("--body", choices=["auto", "real", "sim"], default="real",
                    help="用哪具身体：real=真外骨骼，sim=数字义体，auto=找不到真机就用义体")
    return ap


def make_bridge(a, session):
    """按 --body 选一具身体。两者接口一致，服务本身不关心用的是哪个。"""
    from bridge.ports import find_port
    safety = lambda s: session.monitor.trip(s)      # noqa: E731
    want = a.body
    if want == "auto":
        want = "real" if find_port() else "sim"
    if want == "sim":
        from bridge.sim import SimBridge
        print("身体：数字义体（sim）—— 参数来自真机录制的辨识结果", flush=True)
        return SimBridge(torque_limit=a.limit, ramp_nm_per_s=a.ramp,
                         safety_check=safety, log_dir=a.state_dir)
    print("身体：真外骨骼（real）", flush=True)
    return ExoBridge(port=a.port, torque_limit=a.limit, ramp_nm_per_s=a.ramp,
                     safety_check=safety, log_dir=a.state_dir)


def read_cmd_file(last_seq: int, path: str = CMD_FILE) -> Optional[dict]:
    """读命令文件；序号没涨就当没有新命令。"""
    try:
        with open(path) as f:
            c = json.load(f)
    except Exception:
        return None
    return c if c.get("seq", 0) > last_seq else None


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.keepalive != 0:
        parser.error("--keepalive 力矩脉冲会绕过策略限幅，已停用；请使用 0")
    evomap_key = os.environ.get("EVOMAP_API_KEY", "").strip()
    if evomap_key and not evomap_key.startswith("sk-evomap-"):
        parser.error("EVOMAP_API_KEY 必须是 EvoMap Gateway key（sk-evomap-…）")
    if evomap_key and a.autopilot:
        parser.error("EvoMap 大模型目前只能给建议；请移除 --autopilot")
    os.makedirs(a.state_dir, exist_ok=True)
    cmd_file = os.path.join(a.state_dir, "cmd.json")
    status_file = os.path.join(a.state_dir, "status.json")
    prof = PROFILES[a.profile]
    session = Session(profile=prof, ramp_cap_nm_s=a.ramp)

    cmdq: "queue.Queue[dict]" = queue.Queue()
    hub = None if a.no_web else WebHub(on_command=cmdq.put,
                                       http_port=a.http_port, ws_port=a.ws_port)

    bridge = make_bridge(a, session)
    if hub:
        hub.body = "sim" if hasattr(bridge, "set_gait") else "real"
    memory = None
    decider = None
    decision_pool = None
    decision_future = None
    decision_context = None
    stats = {"n": 0, "work": 0.0, "last_t": None, "scale": 1.0}

    journal = Journal()          # 路径要等 ENABLE 之后才知道，见下面 set_path
    journal_started = False

    def start_journal(version: str) -> None:
        nonlocal journal_started
        if journal_started or not bridge.log_path:
            return
        journal.set_path(os.path.splitext(bridge.log_path)[0] + ".jsonl")
        journal.write("session", phase="start", profile=prof.name, body=a.body,
                      limit=a.limit, ramp=a.ramp, autopilot=a.autopilot,
                      csv=bridge.log_path, version=version)
        journal_started = True

    def log(msg: str, level: str = "info", kind: str = "note", **fields) -> None:
        print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)
        if hub:
            hub.push_event(msg, level)
        journal.write(kind, msg=msg, level=level, **fields)

    # ---------- 逐帧回调（跑在串口读线程里，要快） ----------
    def on_sample(s) -> None:
        quiet = session.in_quiet_period(time.time(), events.LEGS_ONLINE_QUIET_S)
        if quiet or bridge.legs_offline or not session.armed or not bridge.enabled or bridge._reconnecting:
            bridge.set_torque(0.0, 0.0)
            if hub:
                hub.push_sample(s, 0.0, 0.0, 0.0)
            return
        if decider is not None:
            decider.feed(s)                  # O(1)：只是 append 一帧，决策在主循环里做
        pol = session.policy
        tl0, tr0 = pol.torque(s, 1.0)
        sc = session.monitor.assist_scale(s, tl0, tr0) if pol.name == "assist" else 1.0
        tl, tr = pol.torque(s, sc)
        bridge.set_torque(tl, tr)
        stats["scale"] = sc
        stats["n"] += 1
        cl, cr = bridge.commanded
        if hub:
            hub.push_sample(s, cl, cr, sc)
        if stats["last_t"] is not None and abs(s.ldps) < DPS_SATURATION and abs(s.rdps) < DPS_SATURATION:
            dt = s.host_t - stats["last_t"]
            stats["work"] += (cl * math.radians(s.ldps) + cr * math.radians(s.rdps)) * dt
        stats["last_t"] = s.host_t

    bridge.on_sample(on_sample)

    # ---------- 设备事件 ----------
    def on_event(ev: str) -> None:
        if ev in {"stall", "legs_offline"}:
            # 腿板恢复后不得自动沿用失效前的助力/阻力策略。
            session.policy = P.make_policy("zero", 0.0, 1.5)
            bridge.set_torque(0.0, 0.0)
        if ev == "reconnected":
            from control.safety import SafetyMonitor
            session.monitor = SafetyMonitor(prof, warmup_s=events.LEGS_ONLINE_QUIET_S)
            session.legs_online_at = time.time()
            session.policy = P.make_policy("zero", 0.0, 1.5)
            start_journal("reconnected")
        if ev == "legs_online":
            # 实测：腿板上线后 3–10 s 内会有一次 35–40°、1200–1700 °/s 的自检快动
            from control.safety import SafetyMonitor
            session.monitor = SafetyMonitor(prof, warmup_s=events.LEGS_ONLINE_QUIET_S)
            session.legs_online_at = time.time()
            log(events.LEGS_ONLINE_HINT, "warn")
            return
        if ev.startswith("trip:"):
            session.armed = False
            session.policy = P.make_policy("zero", 0.0, 1.5)
        msg, level = events.describe(ev)
        log(msg, level, kind="event", event=ev)
        if memory is not None:               # 出了事先去翻以前踩过的坑
            memory.note(f"设备事件：{ev}", "partial", payload={"event": ev})
            memory.recall_for_event(ev)

    def run_cmd(c: dict, who: str) -> None:
        """所有命令都从这里走：先记流水（谁下的、下了什么），再交给分发器。"""
        journal.write("command", by=who, cmd=dict(c))
        if c.get("op") in {"policy", "hold", "torque"} and (
            not bridge.enabled or bridge._reconnecting or bridge.stream_hz() < 50 or
            session.in_quiet_period(time.time(), events.LEGS_ONLINE_QUIET_S)
        ):
            log("设备未就绪或处于安全等待期，忽略控制命令；请恢复后重新下发", "warn")
            return
        commands.apply(c, session=session, bridge=bridge, log=log)

    bridge.on_event(on_event)

    # ---------- 经验层（慎思，跑在自己的线程上，绝不进串口读线程） ----------
    if not a.no_memory:
        from agent.memory import GhostMemory

        def on_recall(r) -> None:
            if not r.hits:
                extra = f"（有 {r.weak} 条沾边但相似度不够，不拿出来误导）" if r.weak else ""
                log(f"回忆「{r.query}」：库里没有相关经验{extra}", "warn")
                return
            top = r.hits[0]
            log(f"回忆「{r.query}」→ {top.asset.title}（相似度 {top.score:.2f}）", "ok",
                kind="recall", recall=r.to_dict())
            for i, step in enumerate(getattr(top.asset, "strategy_steps", ())[:4], 1):
                log(f"    {i}. {step}")

        memory = GhostMemory(db_path=a.memory_db, on_recall=on_recall).start()
        session.memory = memory

    # ---------- 直觉层（决策，跑在主循环里，不进串口读线程） ----------
    if not a.no_decide:
        from agent.decide import GhostDecider

        def on_decision(d) -> None:
            src = ("本地安全规则" if d.held_by == "safety" else
                   "本地规则（EvoMap 暂不可用）" if evomap_key and d.backend == "rules" else
                   "本地规则" if d.backend == "rules" else "EvoMap Gateway")
            head = f"决策：{d.want}（置信 {d.confidence:.2f}，来自 {src}）"
            if d.held_by == "safety":
                log(f"{head} → 本地安全规则只允许 zero", "warn")
            elif d.held_by == "gate":
                log(f"{head} → 置信度不足 {a.min_confidence}，保持 {d.applied} 不动", "warn")
            elif d.held_by == "hold":
                log(f"{head} → 刚换过策略，{decider.min_hold_s:.0f} 秒内不再改，"
                    f"保持 {d.applied}", "warn")
            elif d.applied == session.policy.name:
                log(f"{head} → 与当前一致，维持 {d.applied}")
            elif d.autopilot:
                log(f"{head} → 自动切换到 {d.applied}", "ok")
            else:
                log(f"{head} → 建议切到 {d.applied}（自动驾驶未开，不下发）")
            log(f"    依据：{d.why}", kind="decision", decision=d.to_dict())

        decider = GhostDecider(period_s=a.decide_period, min_confidence=a.min_confidence,
                               autopilot=a.autopilot,
                               backend="llm" if evomap_key else "rules",
                               api_key=evomap_key or None,
                               base_url=EVOMAP_GATEWAY_BASE_URL if evomap_key else None,
                               model=os.environ.get("EVOMAP_MODEL", EVOMAP_DEFAULT_MODEL) if evomap_key else None)
        decision_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ghost-decide")
        log("直觉层：EvoMap Gateway 仅建议，模型 "
            + os.environ.get("EVOMAP_MODEL", EVOMAP_DEFAULT_MODEL)
            if evomap_key else "直觉层：本地规则，仅建议")

    # 启动时忽略上次遗留的命令文件，避免重放旧策略
    try:
        session.seq = json.load(open(cmd_file)).get("seq", 0)
    except Exception:
        pass

    if hub:
        hub.start()
        print(f"仪表盘：http://localhost:{a.http_port}  "
              f"（手机：http://{lan_ip()}:{a.http_port}）", flush=True)
    version_info = "pending"
    try:
        bridge.open()
        print("PING    ->", bridge.ping())
        version_info = bridge.version()
        print("VERSION ->", version_info)
        print("ENABLE  ->", bridge.enable(send_torque=True))
        if isinstance(bridge, ExoBridge):
            from control.safety import SafetyMonitor
            session.monitor = SafetyMonitor(prof, warmup_s=events.LEGS_ONLINE_QUIET_S)
            session.legs_online_at = time.time()
    except (OSError, RuntimeError, TimeoutError) as e:
        if not isinstance(bridge, ExoBridge):
            raise
        log(f"等待外骨骼串口：{e}", "warn")
        bridge.start_recovery(send_torque=True)
    print(f"安全档 {prof.name}: acc>{prof.acc_trip_g}g gyro>{prof.gyro_trip_dps} "
          f"tilt>{prof.tilt_trip_deg} 关节>{prof.joint_dps_trip}°/s | "
          f"软限幅 ±{a.limit} Nm 斜坡 {a.ramp} Nm/s | 记录 {bridge.log_path}")
    if decider is not None:
        print(f"直觉层：每 {a.decide_period:.0f} 秒决策一次，置信度门槛 {a.min_confidence}，"
              f"自动驾驶 {'开' if a.autopilot else '关（只建议不下发）'}", flush=True)
    if memory is not None:
        memory.wait_boot(3.0)                # 只在启动时等一下，为了能报出继承了几条
        snap = memory.snapshot()
        print(f"经验库 {a.memory_db}：继承了 {snap['inherited']} 条经验"
              f"（本次新播种 {snap['seeded']} 条）", flush=True)
    start_journal(version_info)
    if journal.path:
        print(f"会话流水：{journal.path}（交付单用它生成）", flush=True)
    print(status.HEADER, flush=True)

    last_print = 0.0
    try:
        while True:
            time.sleep(0.2)
            now = time.time()

            # 网络决策只能在工作线程等待；主循环仍需及时处理 zero / estop。
            if (decider is not None and decision_future is None and bridge.enabled
                    and not bridge._reconnecting and decider.due(now)):
                decision_context = (session.armed, bridge.tripped,
                                    bridge.legs_offline, session.policy.name)
                decision_future = decision_pool.submit(
                    decider.tick, now, current_policy=session.policy.name,
                    armed=session.armed, tripped=bridge.tripped,
                    legs_offline=bridge.legs_offline)
            if decision_future is not None and decision_future.done():
                try:
                    d = decision_future.result()
                except Exception as e:
                    d = None
                    log(f"决策层出错（已忽略，不影响控制）：{e}", "err")
                decision_future = None
                current_context = (session.armed, bridge.tripped,
                                   bridge.legs_offline, session.policy.name)
                if decision_context != current_context:
                    d = None                 # 急停、掉线或手动换策略后丢弃旧建议
                if d is not None:
                    on_decision(d)
                if d is not None and decider.autopilot:
                    caps = {"assist": 0.8, "resist": 1.5, "zero": 1.5}   # 项目规则：assist 上限更严
                    if d.applied != session.policy.name:
                        run_cmd({"seq": session.seq, "op": "policy", "policy": d.applied,
                                 "gain": d.gain if d.applied == "assist" else 0.3,
                                 "max": caps.get(d.applied, 1.5)}, "ghost")
                    elif d.applied == "assist":
                        # 已经在助力里：离散的"换不换策略"被门控管着，但连续的增益
                        # 该跟着证据走。置信度不足时只准往下调——加力必须过门控。
                        cur = session.policy.gain
                        want = d.gain if d.confidence >= a.min_confidence else min(d.gain, cur)
                        if abs(want - cur) >= 0.05:
                            arrow = "下调" if want < cur else "上调"
                            log(f"助力增益{arrow} {cur:.2f} → {want:.2f}"
                                f"（步态相似度变了，置信 {d.confidence:.2f}）", "ok")
                            run_cmd({"seq": session.seq, "op": "policy",
                                     "policy": "assist", "gain": want, "max": 0.8}, "ghost")

            # 命令：文件与网页两条来源，同一个分发器
            c = read_cmd_file(session.seq, cmd_file)
            if c:
                session.seq = c["seq"]
                run_cmd(c, "cli")
            while not cmdq.empty():
                run_cmd(cmdq.get(), "web")

            # 每秒一行状态
            if now - last_print >= 1.0:
                last_print = now
                s = bridge.latest
                cl, cr = bridge.commanded
                st = status.device_state(tripped=bridge.tripped, armed=session.armed,
                                         legs_offline=bridge.legs_offline,
                                         reconnecting=bridge._reconnecting,
                                         connected=bridge.enabled and bridge.stream_hz() > 0,
                                         quiet=session.in_quiet_period(now, events.LEGS_ONLINE_QUIET_S))
                if s:
                    print(status.console_line(
                        state=st, policy=session.policy.name, gain=session.policy.gain,
                        hz=bridge.stream_hz(), ldeg=s.ldeg, rdeg=s.rdeg, ldps=s.ldps, rdps=s.rdps,
                        tau_l=cl, tau_r=cr, scale=stats["scale"], work_J=stats["work"]), flush=True)
                else:
                    print(f"{time.strftime('%H:%M:%S'):>8} {st:>8} 等待实时数据", flush=True)
                base = status.snapshot(
                    t=now, state=st, policy=session.policy.name, gain=session.policy.gain,
                    max_torque=session.policy.max_torque, hz=bridge.stream_hz(),
                    work_J=stats["work"], tripped=bridge.tripped,
                    legs_offline=bridge.legs_offline, reconnects=bridge.n_reconnects,
                    scale=stats["scale"], reflex=session.monitor.scale_detail(),
                    memory=None if memory is None else memory.snapshot(),
                    decision=None if decider is None else decider.snapshot())
                base["body"] = "real" if isinstance(bridge, ExoBridge) else "sim"
                base["profile"] = prof.name
                if hub:
                    hub.push_status(base)
                status.write_status_file(status_file, status.full_snapshot(
                    base, ldeg=s.ldeg if s else None, rdeg=s.rdeg if s else None,
                    ldps=s.ldps if s else None, rdps=s.rdps if s else None,
                    tau_l=cl, tau_r=cr, scale=stats["scale"], log=bridge.log_path))
    except KeyboardInterrupt:
        print("\nCtrl-C", flush=True)
    finally:
        if decision_pool is not None:
            decision_pool.shutdown(wait=False, cancel_futures=True)
        journal.write("session", phase="end", frames=stats["n"],
                      work_J=round(stats["work"], 3), reconnects=bridge.n_reconnects,
                      tripped=bridge.tripped,
                      decisions=None if decider is None else decider.n_decisions,
                      held=None if decider is None else decider.n_held,
                      applied=None if decider is None else decider.n_applied)
        print("DISABLE ->", bridge.disable(), flush=True)
        bridge.close()
        if decider is not None:
            print(f"直觉层：决策 {decider.n_decisions} 次，其中 {decider.n_held} 次被门控或安全规则限制，"
                  f"{decider.n_applied} 次自动下发", flush=True)
        if memory is not None:               # 把这次会话沉淀下去再走
            memory.note("会话结束", "success", payload={
                "frames": stats["n"], "work_J": round(stats["work"], 3),
                "profile": prof.name, "reconnects": bridge.n_reconnects,
                "tripped": bridge.tripped,
            })
            memory.close()
            print(f"经验库：本次继承 {memory.inherited} 条，"
                  f"丢弃 {memory.dropped} 个任务，出错 {memory.errors} 次", flush=True)


if __name__ == "__main__":
    main()
