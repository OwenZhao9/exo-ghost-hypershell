"""数字义体：一个跟真机同接口的假设备。

**为什么存在**：真机会掉线、会没电、会在评委面前崩。有了它，拔掉 USB 线
不是事故而是演示的一部分——同一个 Ghost、同一套策略，换一具身体继续跑。
开发时也不用等硬件。

接口与 `bridge.exo.ExoBridge` 一致（`open / ping / version / enable / disable /
set_torque / commanded / on_sample / on_event / latest / stream_hz / close` …），
所以 `runtime/service.py` 一行都不用改。

分工：执行器模型来自通用库 `sim2real_actuator`（摩擦、偏置、限幅），
腿的重力与限位在 `bridge/plant.py`，本文件只负责把它们按真机的节奏跑起来。
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable, Optional

from sim2real_actuator import ActuatorParams, ActuatorSim, identify, load_columns

from .limits import clamp as clamp_torque
from .limits import effective_limit, ramp_step, step_toward
from .faults import FaultInjector
from .logger import SessionLogger
from .plant import DEG2RAD, LegLoad
from .protocol import DEFAULT_LIMIT_NM, DEFAULT_RAMP_NM_PER_S, SEND_HZ, Sample

RAD2DEG = 180.0 / math.pi
STREAM_HZ = 180.0                  # 真机实测约 180 Hz，义体照抄，节奏一致
CALIBRATION_CSV = "data/samples/breakaway-measurement.csv"

# 真机实测兜底值（docs/protocol.md）：辨识不可用时用它们，仍然是真数据
FALLBACK = {
    "L": ActuatorParams(coulomb_nm=0.30, viscous_nm_s_per_rad=0.166,
                        bias_nm=0.22, inertia_kg_m2=0.02, source="实测兜底"),
    "R": ActuatorParams(coulomb_nm=0.40, viscous_nm_s_per_rad=0.011,
                        bias_nm=0.11, inertia_kg_m2=0.02, source="实测兜底"),
}


def identify_from_recording(path: str = CALIBRATION_CSV) -> dict[str, ActuatorParams]:
    """从真实录制里辨识两条腿的执行器参数；失败就用实测兜底值。"""
    out: dict[str, ActuatorParams] = {}
    for leg, tau_col, vel_col, pos_col in (("L", "cmd_l", "ldps", "ldeg"),
                                           ("R", "cmd_r", "rdps", "rdeg")):
        try:
            c = load_columns(path, t="host_t", tau=tau_col, vel=vel_col,
                             pos=pos_col, vel_unit="deg/s")
            p = identify(t_s=c["t_s"], tau_nm=c["tau_nm"], vel_rad_s=c["vel_rad_s"],
                         pos_rad=c["pos_rad"], fit_inertia=False)
            # 惯量在这批录制上不可辨识（角速度量化 0.1°/s），用量级估计补上
            out[leg] = ActuatorParams(
                coulomb_nm=p.coulomb_nm, viscous_nm_s_per_rad=p.viscous_nm_s_per_rad,
                bias_nm=p.bias_nm, inertia_kg_m2=0.02,
                source=f"{path}:{tau_col}")
        except Exception:
            out[leg] = FALLBACK[leg]
    return out


class SimBridge:
    """数字义体。与 ExoBridge 同接口，不开串口、不碰硬件。"""

    def __init__(self, port: Optional[str] = None,
                 torque_limit: float = DEFAULT_LIMIT_NM,
                 ramp_nm_per_s: float = DEFAULT_RAMP_NM_PER_S,
                 send_hz: int = SEND_HZ,
                 log_dir: Optional[str] = "data",
                 safety_check: Optional[Callable[[Sample], Optional[str]]] = None,
                 params: Optional[dict[str, ActuatorParams]] = None,
                 load: Optional[LegLoad] = None,
                 speed: float = 1.0):
        self.port = port or "sim://digital-twin"
        self.torque_limit = effective_limit(torque_limit)
        self.send_period = 1.0 / send_hz
        self.ramp_step = ramp_step(ramp_nm_per_s, self.send_period)
        self.safety_check = safety_check
        self.speed = speed
        self.params = params or identify_from_recording()
        self.load = load or LegLoad()

        self.sims = {k: ActuatorSim(v) for k, v in self.params.items()}
        # ActuatorSim 只暴露 step/reset，位置速度由本类自己跟着记（它是被控对象的状态）
        self.state = {k: (0.0, 0.0) for k in self.sims}   # leg -> (pos_rad, vel_rad_s)
        self.latest: Optional[Sample] = None
        self.enabled = False
        self.tripped: Optional[str] = None
        self.legs_offline = False
        self.n_reconnects = 0
        self.n_samples = 0
        self.last_err: Optional[str] = None
        self._reconnecting = False
        self._device_disabled = False

        self._target = (0.0, 0.0)
        self._current = (0.0, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._times: deque[float] = deque(maxlen=400)
        self._on_sample: list[Callable[[Sample], None]] = []
        self._on_event: list[Callable[[str], None]] = []
        self._logger = SessionLogger(log_dir, prefix="sim")
        self._t0 = 0.0
        self.faults = FaultInjector()        # 按需复现真机故障，见 bridge/faults.py

    # ---------- 与 ExoBridge 一致的门面 ----------
    def open(self) -> "SimBridge":
        return self

    def ping(self) -> str:
        return "PONG(sim)"

    def version(self) -> str:
        return "OK,VERSION,sim-digital-twin"

    def on_sample(self, cb: Callable[[Sample], None]) -> None:
        self._on_sample.append(cb)

    def on_event(self, cb: Callable[[str], None]) -> None:
        self._on_event.append(cb)

    def _emit(self, ev: str) -> None:
        for cb in self._on_event:
            try:
                cb(ev)
            except Exception as e:
                self.last_err = f"callback: {e}"

    @property
    def log_path(self) -> Optional[str]:
        return self._logger.path

    @property
    def commanded(self) -> tuple[float, float]:
        return self._current

    def set_ramp(self, nm_per_s: float) -> None:
        self.ramp_step = ramp_step(nm_per_s, self.send_period)

    @property
    def ramp_nm_per_s(self) -> float:
        return self.ramp_step / self.send_period

    def set_torque(self, left: float, right: float) -> None:
        with self._lock:
            self._target = (clamp_torque(left, self.torque_limit),
                            clamp_torque(right, self.torque_limit))

    def trip(self, reason: str) -> None:
        self.tripped = reason
        self.set_torque(0.0, 0.0)
        self.enabled = False
        self._device_disabled = True
        self._emit(f"trip:{reason}")

    def rearm(self, send_torque: bool = True) -> str:
        self.tripped = None
        self._device_disabled = False
        return self.enable(send_torque=send_torque)

    def enable(self, send_torque: bool = False) -> str:
        self.enabled = True
        self.tripped = None
        self._current = (0.0, 0.0)
        self._target = (0.0, 0.0)
        self._logger.open()
        self._t0 = time.time()
        for leg, sim in self.sims.items():                     # 每次 ENABLE 从中立位开始
            sim.reset(pos_rad=0.0, vel_rad_s=0.0)
            self.state[leg] = (0.0, 0.0)
        self._stop.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="sim-body", daemon=True)
            self._thread.start()
        return "OK,ENABLE(sim)"

    def disable(self) -> Optional[str]:
        self.enabled = False
        self._stop.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=0.5)
        self._current = (0.0, 0.0)
        return "OK,DISABLE(sim)"

    def stream_hz(self) -> float:
        now = time.time()
        return float(sum(1 for t in list(self._times) if now - t <= 1.0))

    def close(self) -> None:
        self.disable()
        self._logger.close()

    # ---------- 身体本身 ----------
    def _run(self) -> None:
        dt = 1.0 / STREAM_HZ
        next_t = time.perf_counter()
        ms = 0.0
        while not self._stop.is_set():
            with self._lock:
                tl, tr = self._target
            cl, cr = self._current
            cl = step_toward(cl, tl, self.ramp_step)
            cr = step_toward(cr, tr, self.ramp_step)
            self._current = (cl, cr)

            states = {}
            for leg, tau in (("L", cl), ("R", cr)):
                sim = self.sims[leg]
                pos0, vel0 = self.state[leg]
                ext = self.load.external_nm(pos0, vel0)
                st = sim.step(tau, dt, external_nm=ext)
                pos, vel = self.load.clamp(st.pos_rad, st.vel_rad_s)
                if (pos, vel) != (st.pos_rad, st.vel_rad_s):
                    sim.reset(pos_rad=pos, vel_rad_s=vel)      # 撞到限位就吸附回去
                self.state[leg] = (pos, vel)
                states[leg] = (pos * RAD2DEG, vel * RAD2DEG)

            ldeg, ldps = states["L"]
            rdeg, rdps = states["R"]
            ms += dt * 1000.0
            now = time.time()
            # 腰部 IMU：义体不会摔倒，给一个静止直立的合理读数
            s = Sample(host_t=now, ms=ms, pitch=0.0, roll=0.0, yaw=0.0,
                       gx=0.0, gy=0.0, gz=0.0, ax=0.0, ay=0.0, az=1.0,
                       kpa=101.0, ldeg=ldeg, rdeg=rdeg, ldps=ldps, rdps=rdps,
                       cmd_l=cl, cmd_r=cr)
            # 故障注入：可能改写这一帧，也可能整帧丢掉（模拟串口断开）
            s, injected = self.faults.step(now, s)
            for ev in injected:
                if ev == "legs_offline":
                    self.legs_offline = True
                    self.set_torque(0.0, 0.0)
                elif ev == "legs_online":
                    self.legs_offline = False
                elif ev == "stall":
                    self._reconnecting = True
                elif ev == "reconnected":
                    self._reconnecting = False
                    self.n_reconnects += 1
                self._emit(ev)

            if s is not None:
                self.latest = s
                self.n_samples += 1
                self._times.append(now)
                self._logger.write(s)
                if self.safety_check and self.enabled:
                    why = self.safety_check(s)
                    if why:
                        self.trip(why)
                for cb in self._on_sample:
                    try:
                        cb(s)
                    except Exception as e:
                        self.last_err = f"callback: {e}"

            next_t += dt / max(self.speed, 1e-6)
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter()
