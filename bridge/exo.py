"""ExoBridge：把协议、端口、限幅、落盘组装成一个能用的设备门面。

本文件负责**有副作用的那一半**：串口收发线程、命令应答、力矩续发、
断流监督与自动重连、腿板掉线检测、生命周期。纯逻辑都在隔壁：

    protocol.py  数据帧与常量（纯）
    ports.py     设备发现（纯）
    limits.py    限幅与斜坡（纯）
    logger.py    CSV 落盘

分层约定：本层只跟设备说话，**不含任何控制策略**——策略在 control/ 里。

待办：收发线程（transport）与故障恢复（recovery）还在本文件里，
将来可以再拆出去；拆之前需要给线程部分补上测试。
"""
from __future__ import annotations

import atexit
import math
import threading
import time
from collections import deque
from typing import Callable, Optional

import serial  # pyserial

from .limits import clamp, effective_limit, ramp_step, step_toward
from .logger import SessionLogger
from .ports import find_port, permission_hint, port_candidates
from .protocol import (
    BAUD,
    DEFAULT_LIMIT_NM,
    DEFAULT_RAMP_NM_PER_S,
    DPS_SATURATION,
    FIRMWARE_LIMIT_NM,
    SEND_HZ,
    STALL_S,
    STREAM_FIELDS,
    WATCHDOG_S,
    Sample,
    parse_stream_line,
)

__all__ = ["ExoBridge", "default_safety"]


class ExoBridge:
    """
    用法：
        b = ExoBridge()            # 自动找 /dev/cu.usbmodem*
        b.open(); b.ping(); b.version()
        b.enable(send_torque=True) # 开数据流；send_torque=True 时启动 200 Hz 续发线程
        b.set_torque(0.5, 0.0)     # 目标力矩，经软限幅 + 斜坡后下发
        ... b.latest 是最新一帧 ...
        b.close()                  # 任何路径退出都会 DISABLE
    """

    def __init__(self, port: Optional[str] = None, baud: int = BAUD,
                 torque_limit: float = DEFAULT_LIMIT_NM,
                 ramp_nm_per_s: float = DEFAULT_RAMP_NM_PER_S,
                 send_hz: int = SEND_HZ,
                 log_dir: Optional[str] = "data",
                 safety_check: Optional[Callable[[Sample], Optional[str]]] = None):
        self.port = port
        self.baud = baud
        self.torque_limit = effective_limit(torque_limit)
        self.send_period = 1.0 / send_hz
        self.ramp_step = ramp_step(ramp_nm_per_s, self.send_period)   # 每个发送周期允许的最大变化
        self.log_dir = log_dir
        self.safety_check = safety_check                   # 返回非空字符串即触发急停

        self.ser: Optional[serial.Serial] = None
        self.latest: Optional[Sample] = None
        self.enabled = False
        self.tripped: Optional[str] = None                 # 急停原因
        self._target = (0.0, 0.0)
        self._current = (0.0, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._sender: Optional[threading.Thread] = None
        self._zero_on_exit = True
        self._responses: deque[str] = deque(maxlen=200)
        self._resp_cv = threading.Condition()
        self._sample_times: deque[float] = deque(maxlen=400)
        self.n_samples = 0
        self.n_bad_lines = 0
        self.n_err = 0
        self.last_err: Optional[str] = None
        self._logger = SessionLogger(log_dir)
        self._on_sample: list[Callable[[Sample], None]] = []
        self._on_event: list[Callable[[str], None]] = []
        self.last_sample_t: float = 0.0
        self.n_reconnects = 0
        self._zero_joint_frames = 0
        self.legs_offline = False
        self._device_disabled = False       # 已经向设备发过 DISABLE（避免重复发再吃 ERR）
        self._enabled_at = 0.0
        self._send_torque_flag = False
        self._supervisor: Optional[threading.Thread] = None
        self._reconnecting = False
        self._reconnect_lock = threading.Lock()
        self._recovery_thread: Optional[threading.Thread] = None
        atexit.register(self.close)

    # ---------- 连接 ----------
    def open(self) -> "ExoBridge":
        if self.port is None:
            self.port = find_port()
        if self.port is None:
            raise RuntimeError("没找到串口（/dev/cu.usbserial* / usbmodem*）：检查外骨骼是否开机、USB 线是否能传数据")
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05, write_timeout=0.2)
        except serial.SerialException as e:
            hint = permission_hint(self.port, e)
            if hint:
                raise RuntimeError(hint) from e
            raise
        time.sleep(0.05)
        self.ser.reset_input_buffer()
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, name="exo-reader", daemon=True)
        self._reader.start()
        self._start_supervisor()
        return self

    def _start_supervisor(self) -> None:
        """启动持续断流监测，也覆盖服务先启动、串口稍后才出现的路径。"""
        if self._supervisor is None or not self._supervisor.is_alive():
            self._supervisor = threading.Thread(target=self._supervise, name="exo-supervisor", daemon=True)
            self._supervisor.start()

    def on_sample(self, cb: Callable[[Sample], None]) -> None:
        self._on_sample.append(cb)

    def on_event(self, cb: Callable[[str], None]) -> None:
        """事件回调：'stall' / 'reconnected' / 'reconnect_failed' / 'trip:<原因>'"""
        self._on_event.append(cb)

    def start_recovery(self, send_torque: bool = True) -> None:
        """启动后台持续找设备；允许服务在未插串口时先打开仪表盘。"""
        self._send_torque_flag = send_torque
        if self._stop.is_set() or self.tripped:
            return
        self._start_supervisor()
        if self._recovery_thread and self._recovery_thread.is_alive():
            return
        self._recovery_thread = threading.Thread(target=self._reconnect, name="exo-recovery", daemon=True)
        self._recovery_thread.start()

    def _emit(self, ev: str) -> None:
        for cb in self._on_event:
            try: cb(ev)
            except Exception: pass

    # ---------- 命令 ----------
    def _write_line(self, s: str) -> None:
        assert self.ser is not None
        self.ser.write((s + "\n").encode("ascii"))

    def command(self, cmd: str, expect_prefix: str, timeout: float = 1.0) -> str:
        """发一条命令，等一行以 expect_prefix 开头的应答"""
        with self._resp_cv:
            self._responses.clear()
        self._write_line(cmd)
        deadline = time.time() + timeout
        with self._resp_cv:
            while True:
                for r in list(self._responses):
                    if r.startswith(expect_prefix):
                        return r
                    if r.startswith("ERR"):
                        raise RuntimeError(f"{cmd} -> {r}")
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"{cmd}: {timeout}s 内没等到 {expect_prefix!r}（收到：{list(self._responses)[-5:]}）")
                self._resp_cv.wait(remaining)

    def ping(self) -> str:
        return self.command("PING", "PONG")

    def version(self) -> str:
        return self.command("VERSION", "OK,VERSION")

    def enable(self, send_torque: bool = False) -> str:
        r = self.command("ENABLE", "OK,ENABLE")
        self.enabled = True
        self.tripped = None
        self._device_disabled = False
        self._current = (0.0, 0.0)
        self._target = (0.0, 0.0)
        self._open_log()
        self._send_torque_flag = send_torque
        self.last_sample_t = time.time()
        self._enabled_at = time.time()
        if send_torque:
            self._sender = threading.Thread(target=self._send_loop, name="exo-sender", daemon=True)
            self._sender.start()
        return r

    def disable(self) -> Optional[str]:
        """力矩清零并停流。无论如何都尝试发出 DISABLE。"""
        self.enabled = False
        self._target = (0.0, 0.0)
        if self._sender and self._sender.is_alive() and threading.current_thread() is not self._sender:
            self._sender.join(timeout=0.5)
        if not self.ser or not self.ser.is_open:
            return None
        if self._device_disabled:
            return "OK,DISABLE(已在急停时发送)"
        try:
            r = self.command("DISABLE", "OK,DISABLE", timeout=0.5)
            self._device_disabled = True
            return r
        except Exception:
            try:
                self._write_line("DISABLE")
            except Exception:
                pass
            return None

    # ---------- 力矩 ----------
    def set_ramp(self, nm_per_s: float) -> None:
        """运行时调整力矩斜坡（每秒最多变化多少 Nm）。越小越柔和。"""
        self.ramp_step = ramp_step(nm_per_s, self.send_period)

    @property
    def ramp_nm_per_s(self) -> float:
        return self.ramp_step / self.send_period

    def set_torque(self, left: float, right: float) -> None:
        """设置目标力矩（Nm）。经软限幅；实际下发再经斜坡。"""
        l = clamp(left, self.torque_limit)
        r = clamp(right, self.torque_limit)
        with self._lock:
            self._target = (l, r)

    def trip(self, reason: str) -> None:
        """急停：目标归零、停止续发、裸发 DISABLE（不等应答，因为可能是在读线程里被调用）"""
        self.tripped = reason
        self.set_torque(0.0, 0.0)
        self.enabled = False
        self._zero_on_exit = False          # 下面手动发，避免和 sender 的退出补发重复
        if self._sender and self._sender.is_alive() and threading.current_thread() is not self._sender:
            self._sender.join(timeout=0.3)
        self._zero_on_exit = True
        try:
            self._write_line("T,0.000,0.000")
            self._write_line("DISABLE")
        except Exception:
            pass
        self._device_disabled = True
        self._emit(f"trip:{reason}")

    @property
    def commanded(self) -> tuple[float, float]:
        return self._current

    def stop_sender(self, zero_on_exit: bool = True) -> float:
        """停止 200 Hz 续发线程。zero_on_exit=False 用于验证固件看门狗：突然沉默，设备应在 100 ms 内自行清零。
        返回停止时刻 time.perf_counter()。之后仍需 disable()。"""
        self._zero_on_exit = zero_on_exit
        self.enabled = False
        t = time.perf_counter()
        if self._sender and self._sender.is_alive() and threading.current_thread() is not self._sender:
            self._sender.join(timeout=0.5)
        self._zero_on_exit = True
        return t

    def _send_loop(self) -> None:
        """200 Hz 续发：每个周期把当前值向目标推进不超过 ramp_step，然后发 T,l,r"""
        next_t = time.perf_counter()
        step = self.ramp_step
        while self.enabled and not self._stop.is_set():
            with self._lock:
                tl, tr = self._target
            cl, cr = self._current
            cl = step_toward(cl, tl, step)
            cr = step_toward(cr, tr, step)
            self._current = (cl, cr)
            try:
                self._write_line(f"T,{cl:.3f},{cr:.3f}")
            except Exception as e:
                self.last_err = f"write: {e}"
                break
            next_t += self.send_period
            dt = next_t - time.perf_counter()
            if dt > 0:
                time.sleep(dt)
            else:
                next_t = time.perf_counter()  # 掉拍了就从现在重新计时
        # 退出发送循环前把力矩归零（看门狗 100 ms 也会兜底）；看门狗测试时故意不发
        if self._zero_on_exit:
            try:
                self._write_line("T,0.000,0.000")
            except Exception:
                pass
        self._current = (0.0, 0.0)

    # ---------- 读 ----------
    def _read_loop(self) -> None:
        buf = bytearray()
        ser = self.ser
        while not self._stop.is_set() and ser and ser.is_open:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except Exception as e:
                self.last_err = f"read: {e}"
                break   # 交给 supervisor 判定停流并重连
            if not chunk:
                continue
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = bytes(buf[:nl]); del buf[:nl + 1]
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                self._handle_line(line)
            if len(buf) > 65536:       # 没有换行的垃圾数据，防爆
                buf.clear(); self.n_bad_lines += 1

    def _handle_line(self, line: str) -> None:
        now = time.time()
        if line.startswith("S:"):
            cl, cr = self._current
            s = parse_stream_line(line, now, cl, cr)
            if s is None:
                self.n_bad_lines += 1
                return
            self.latest = s
            self.n_samples += 1
            self.last_sample_t = now
            self._sample_times.append(now)
            # 腿部电机板掉线的特征：四个关节字段精确为 0（实测主板重启后会这样）
            if s.ldeg == 0.0 and s.rdeg == 0.0 and s.ldps == 0.0 and s.rdps == 0.0:
                self._zero_joint_frames += 1
                if self._zero_joint_frames == 180 and not self.legs_offline:
                    self.legs_offline = True
                    self._emit("legs_offline")
            else:
                if self.legs_offline:
                    self.legs_offline = False
                    self._emit("legs_online")
                self._zero_joint_frames = 0
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
            return
        if line.startswith("OK,T,"):
            return                                   # 200 Hz 的力矩回执，忽略
        if line.startswith("ERR"):
            self.n_err += 1
            self.last_err = line
            if line.startswith("ERR,NOT_ENABLED") and self.enabled and not self.tripped and not self._reconnecting:
                # 我们以为在使能，设备说没有 → 设备侧复位过（主板重启等），立刻重新 ENABLE
                self._emit("device_lost_enable")
                self.start_recovery(send_torque=self._send_torque_flag)
        with self._resp_cv:
            self._responses.append(line)
            self._resp_cv.notify_all()

    def rearm(self, send_torque: bool = True) -> str:
        """急停锁存后重新武装：清标志、（必要时重开串口）、重新 ENABLE、重启续发线程。调用方负责先确认现场安全。"""
        self.tripped = None
        self.enabled = False
        if self._sender and self._sender.is_alive() and threading.current_thread() is not self._sender:
            self._sender.join(timeout=0.5)
        self._device_disabled = False
        # 串口可能在急停期间被拔过（设备断电重启），先探测，不通就重开
        alive = False
        try:
            if self.ser and self.ser.is_open and self._reader and self._reader.is_alive():
                self.ping(); alive = True
        except Exception:
            alive = False
        if not alive:
            self._reopen_port()
        return self.enable(send_torque=send_torque)

    def _reopen_port(self) -> None:
        """关掉旧串口和读线程，重新找设备名（可能变了）并打开。"""
        old_stop = self._stop
        self._stop = threading.Event()
        old_stop.set()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        if self._reader and self._reader.is_alive() and threading.current_thread() is not self._reader:
            self._reader.join(timeout=0.5)
        last_err = None
        for attempt in range(10):
            port = find_port()
            if port:
                try:
                    self.port = port
                    self.ser = serial.Serial(port, self.baud, timeout=0.05, write_timeout=0.2)
                    time.sleep(0.05); self.ser.reset_input_buffer()
                    self._reader = threading.Thread(target=self._read_loop, name="exo-reader", daemon=True)
                    self._reader.start()
                    self.ping()
                    return
                except Exception as e:
                    last_err = e
                    try:
                        if self.ser: self.ser.close()
                    except Exception:
                        pass
            time.sleep(0.5)
        raise RuntimeError(f"串口重开失败（{last_err}）：设备开机了吗？线插好了吗？")

    # ---------- 断流监督与重连 ----------
    def _supervise(self) -> None:
        low_since = None
        while not self._stop.is_set():
            time.sleep(0.05)
            if not self.enabled or self._reconnecting or self.tripped:
                continue
            now = time.time()
            if now - self._enabled_at < 2.5:          # 刚 ENABLE 的头两秒频率窗口还没填满，不判定
                continue
            if self.last_sample_t and now - self.last_sample_t > STALL_S:
                self._reconnect(); low_since = None; continue
            # 数据流明显变慢（设备正在死掉/重启）：先把力矩清零，持续 1 s 就当停流处理
            if self.last_sample_t and now - self.last_sample_t > 1.5 or self.stream_hz() < 100:
                if now - (self.last_sample_t or now) > 2.0 or (low_since and now - low_since > 1.0):
                    self._reconnect(); low_since = None; continue
                if low_since is None:
                    low_since = now
                    self.set_torque(0.0, 0.0)
                    self._emit("stream_slow")
            else:
                low_since = None

    def _reconnect(self) -> None:
        """断流或启动时无设备：始终轮询所有候选端口，验证协议后以零力矩恢复。"""
        if not self._reconnect_lock.acquire(blocking=False):
            return
        try:
            self._reconnecting = True
            self.enabled = False
            self.set_torque(0.0, 0.0)
            self._emit("stall")
            if self._sender and self._sender.is_alive() and threading.current_thread() is not self._sender:
                self._sender.join(timeout=0.5)
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            if self._reader and self._reader.is_alive() and threading.current_thread() is not self._reader:
                self._reader.join(timeout=0.5)
            self.ser = None
            self.latest = None
            self._sample_times.clear()
            attempt = 0
            while not self._stop.is_set() and not self.tripped:
                candidates = port_candidates(self.port)
                for port in candidates:
                    if self._stop.is_set() or self.tripped:
                        break
                    attempt += 1
                    try:
                        self.ser = serial.Serial(port, self.baud, timeout=0.05, write_timeout=0.2)
                        time.sleep(0.05)
                        self.ser.reset_input_buffer()
                        self._reader = threading.Thread(target=self._read_loop, name="exo-reader", daemon=True)
                        self._reader.start()
                        self.ping()
                        self.version()  # 只接收本项目固件，不把其他串口设备 ENABLE
                        self.command("ENABLE", "OK,ENABLE")
                        if self._stop.is_set() or self.tripped:
                            self.disable()
                            break
                        self.port = port
                        self._current = (0.0, 0.0)
                        self.set_torque(0.0, 0.0)
                        self.last_sample_t = time.time()
                        self._enabled_at = self.last_sample_t
                        self._device_disabled = False
                        self._open_log()
                        self.n_reconnects += 1
                        self._emit("reconnected")
                        self.enabled = True
                        self._reconnecting = False
                        if self._send_torque_flag:
                            self._sender = threading.Thread(target=self._send_loop, name="exo-sender", daemon=True)
                            self._sender.start()
                        return
                    except Exception as e:
                        self.last_err = f"reconnect#{attempt} {port}: {e}"
                        try:
                            if self.ser:
                                self.ser.close()
                        except Exception:
                            pass
                        if self._reader and self._reader.is_alive():
                            self._reader.join(timeout=0.2)
                        self.ser = None
                self._stop.wait(0.25)  # 热插拔后下一轮立即扫描；不设重试次数上限
        finally:
            self._reconnecting = False
            self._reconnect_lock.release()

    # ---------- 状态 ----------
    def stream_hz(self) -> float:
        """最近 1 秒内的数据流频率。读线程会并发 append，先做快照再统计。"""
        now = time.time()
        try:
            snap = list(self._sample_times)
        except RuntimeError:                      # 极少数情况下 deque 正在被修改
            snap = list(self._sample_times)
        return float(sum(1 for t in snap if now - t <= 1.0))

    # ---------- 落盘 ----------
    @property
    def log_path(self) -> Optional[str]:
        """当前会话的 CSV 路径（未开启落盘时为 None）。"""
        return self._logger.path

    def _open_log(self) -> None:
        self._logger.open()

    def close(self) -> None:
        # 正常连接时先让读线程接收 DISABLE 应答；正在找端口时先取消恢复线程。
        if self._reconnecting:
            self._stop.set()
        try:
            if self.ser is not None:
                self.disable()
        finally:
            self._stop.set()
            if self._recovery_thread and self._recovery_thread.is_alive() and threading.current_thread() is not self._recovery_thread:
                self._recovery_thread.join(timeout=0.5)
            if self._reader and self._reader.is_alive() and threading.current_thread() is not self._reader:
                self._reader.join(timeout=0.5)
            self._logger.close()
            try:
                if self.ser is not None:
                    self.ser.close()
            finally:
                self.ser = None


# ---------- 可选的安全检查（穿戴时启用；桌面测试默认不启用） ----------
def default_safety(acc_limit_g: float = 3.0, tilt_limit_deg: float = 60.0) -> Callable[[Sample], Optional[str]]:
    """腰部加速度模长突增或倾角过大 → 急停。阈值在真机上校准后再调。"""
    def check(s: Sample) -> Optional[str]:
        a = math.sqrt(s.ax * s.ax + s.ay * s.ay + s.az * s.az)
        if a > acc_limit_g:
            return f"加速度 {a:.1f} g 超过 {acc_limit_g} g"
        if abs(s.roll) > tilt_limit_deg or abs(s.pitch) > tilt_limit_deg:
            return f"倾角 roll={s.roll:.0f} pitch={s.pitch:.0f} 超过 {tilt_limit_deg}°"
        return None
    return check
