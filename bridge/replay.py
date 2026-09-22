"""回放：把 data/session_*.csv 当成设备在说话，接口与 ExoBridge 对齐（latest / on_sample / stream_hz）。
没有硬件时用它开发控制器、Agent、仪表盘。
用法：from bridge.replay import ReplayBridge; b = ReplayBridge("data/xxx.csv").open()
"""
from __future__ import annotations
import csv, threading, time
from collections import deque
from typing import Callable, Optional
from bridge.serial_io import Sample

class ReplayBridge:
    def __init__(self, path: str, speed: float = 1.0, loop: bool = True):
        self.path, self.speed, self.loop = path, speed, loop
        self.latest: Optional[Sample] = None
        self.enabled = False
        self._on_sample: list[Callable[[Sample], None]] = []
        self._times: deque[float] = deque(maxlen=400)
        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None
        self._target = (0.0, 0.0)
        self.n_samples = 0

    def open(self): return self
    def ping(self): return "PONG(replay)"
    def version(self): return "OK,VERSION,replay"
    def on_sample(self, cb): self._on_sample.append(cb)
    def set_torque(self, l, r): self._target = (float(l), float(r))
    @property
    def commanded(self): return self._target
    def stream_hz(self):
        now = time.time(); return float(len([t for t in self._times if now - t <= 1.0]))

    def enable(self, send_torque: bool = False):
        self.enabled = True; self._stop.clear()
        self._t = threading.Thread(target=self._run, daemon=True); self._t.start()
        return "OK,ENABLE(replay)"

    def disable(self):
        self.enabled = False; self._stop.set(); return "OK,DISABLE(replay)"

    def close(self): self.disable()

    def _rows(self):
        with open(self.path, newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                yield {k: float(v) for k, v in row.items()}

    def _run(self):
        while not self._stop.is_set():
            prev_ms = None; t_prev = time.perf_counter()
            for row in self._rows():
                if self._stop.is_set(): return
                ms = row["ms"]
                if prev_ms is not None:
                    dt = max(0.0, (ms - prev_ms) / 1000.0) / self.speed
                    t_prev += dt
                    sl = t_prev - time.perf_counter()
                    if sl > 0: time.sleep(sl)
                prev_ms = ms
                row["host_t"] = time.time()
                s = Sample(**row)
                self.latest = s; self.n_samples += 1; self._times.append(time.time())
                for cb in self._on_sample: cb(s)
            if not self.loop: return
