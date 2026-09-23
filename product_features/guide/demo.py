"""Opt-in, sequential Luma photo capture for a supervised local demo.

Each capture completes before the next begins. A failed capture never reuses an
older image for a new decision, and this module has no exoskeleton control path.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .vision import analyze_demo_jpeg, photo_path

UNIT_NAME = re.compile(r'E\d{2}-[0-9A-F]{4}\Z')


class DemoCapture:
    def __init__(self, binary: Path, directory: Path, unit: str, *, recognize: bool,
                 pause_seconds: float = 3, max_frames: int = 10):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError('眼镜拍照程序不存在或不可执行')
        if not directory.is_dir():
            raise ValueError('眼镜照片目录不存在')
        if not UNIT_NAME.fullmatch(unit):
            raise ValueError('眼镜蓝牙名称无效')
        if not 1 <= max_frames <= 30:
            raise ValueError('演示拍照数量需要在 1 到 30 张之间')
        self.binary = binary.resolve()
        self.directory = directory.resolve()
        self.unit = unit
        self.recognize = recognize
        self.pause_seconds = max(2, pause_seconds)
        self.max_frames = max_frames
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._state = {'running': False, 'phase': 'idle', 'filename': None,
                       'captured_at': None, 'capture_seconds': None,
                       'analysis_seconds': None, 'direction': 'unknown',
                       'description': '', 'error': None, 'sequence': 0,
                       'captured_count': 0, 'max_frames': max_frames,
                       'recognize_enabled': recognize}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self) -> dict:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._state)
            self._stop.clear()
            self._state.update(running=True, phase='scanning', error=None,
                               direction='unknown', description='', captured_count=0)
            self._thread = threading.Thread(target=self._run, name='glasses-demo', daemon=True)
            self._thread.start()
            return dict(self._state)

    def stop(self) -> dict:
        self._stop.set()
        with self._lock:
            process = self._process
            if self._state['running']:
                self._state['phase'] = 'stopping'
            state = dict(self._state)
        if process is not None and process.poll() is None:
            process.terminate()
        return state

    def close(self) -> None:
        self.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    def _capture(self) -> tuple[Path, float]:
        if self._stop.is_set():
            raise InterruptedError
        name = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-glasses.jpg'
        target = self.directory / name
        env = dict(os.environ, LUMA_UNIT=self.unit)
        started = time.monotonic()
        process = subprocess.Popen([str(self.binary), 'photo', '--ai', str(target)],
                                   cwd=self.binary.parent, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with self._lock:
            self._process = process
            if self._stop.is_set():
                process.terminate()
        try:
            process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ValueError('眼镜拍照超时') from None
        finally:
            with self._lock:
                self._process = None
        if self._stop.is_set():
            raise InterruptedError
        if process.returncode != 0:
            raise ValueError('眼镜拍照失败，请检查眼镜电量、蓝牙连接和占用情况')
        checked = photo_path(self.directory, name)
        return checked, time.monotonic() - started

    def _run(self) -> None:
        errors = 0
        try:
            while not self._stop.is_set():
                try:
                    self._set(phase='capturing', error=None)
                    path, capture_seconds = self._capture()
                    captured_at = path.stat().st_mtime
                    self._set(filename=path.name, captured_at=captured_at,
                              capture_seconds=round(capture_seconds, 1),
                              analysis_seconds=None, phase='analyzing' if self.recognize else 'waiting',
                              direction='unknown', description='',
                              sequence=self.status()['sequence'] + 1,
                              captured_count=self.status()['captured_count'] + 1)
                    if self.recognize and not self._stop.is_set():
                        started = time.monotonic()
                        decision = analyze_demo_jpeg(path.read_bytes())
                        if not self._stop.is_set():
                            self._set(direction=decision['direction'],
                                      description=decision['description'],
                                      analysis_seconds=round(time.monotonic() - started, 1),
                                      phase='waiting')
                    errors = 0
                except InterruptedError:
                    break
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    if not self._stop.is_set():
                        errors += 1
                        self._set(phase='error', error=str(error), direction='unknown',
                                  description='')
                if self.status()['captured_count'] >= self.max_frames or errors >= 3:
                    break
                self._stop.wait(max(self.pause_seconds, 15 if errors else 0))
        finally:
            self._set(running=False, phase='idle')
