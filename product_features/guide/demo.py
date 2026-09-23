"""Supervised Luma demo with independent capture and recognition workers."""
from __future__ import annotations

import os
import queue
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .decision import decide_visual_cue
from .vision import analyze_demo_jpeg, photo_path

UNIT_NAME = re.compile(r'E\d{2}-[0-9A-F]{4}\Z')


class DemoCapture:
    def __init__(self, binary: Path, directory: Path, unit: str, *, recognize: bool,
                 pause_seconds: float = 3, max_frames: int = 10, store=None):
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
        self.pause_seconds = max(0, pause_seconds)
        self.max_frames = max_frames
        self.store = store
        try:
            saved = store.get('guide_demo_history', []) if store is not None else []
        except sqlite3.Error:
            raise ValueError('无法读取本机拍照记录') from None
        self._history = ([{**item, 'state': 'interrupted' if item.get('state') in
                           {'queued', 'analyzing'} else item.get('state', 'interrupted')}
                          for item in saved if isinstance(item, dict) and
                          isinstance(item.get('filename'), str)]
                         if isinstance(saved, list) else [])
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._stop = threading.Event()
        self._capture_done = threading.Event()
        self._analysis_done = threading.Event()
        self._capture_done.set()
        self._analysis_done.set()
        self._queue: queue.Queue[str] = queue.Queue()
        self._capture_thread: threading.Thread | None = None
        self._analysis_thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._state = {'running': False, 'phase': 'idle', 'filename': None,
                       'captured_at': None, 'capture_seconds': None,
                       'analysis_seconds': None, 'direction': 'unknown',
                       'description': '', 'error': None, 'sequence': len(self._history),
                       'captured_count': 0, 'max_frames': max_frames,
                       'recognize_enabled': recognize}

    def _snapshot_locked(self) -> dict:
        return {**self._state,
                'capture_running': self._state['running'] and not self._capture_done.is_set(),
                'analysis_running': self._state['running'] and not self._analysis_done.is_set(),
                'pending_count': sum(item.get('state') in {'queued', 'analyzing'}
                                     for item in self._history),
                'history': [dict(item) for item in self._history]}

    def status(self) -> dict:
        with self._lock:
            return self._snapshot_locked()

    def start(self) -> dict:
        with self._lock:
            if self._state['running']:
                return self._snapshot_locked()
            self._stop.clear()
            self._capture_done.clear()
            if self.recognize:
                self._analysis_done.clear()
            else:
                self._analysis_done.set()
            self._queue = queue.Queue()
            self._state.update(running=True, phase='scanning', error=None,
                               direction='unknown', description='', captured_count=0)
            self._capture_thread = threading.Thread(target=self._run_capture,
                                                     name='glasses-capture', daemon=True)
            self._analysis_thread = (threading.Thread(target=self._run_analysis,
                                                       name='glasses-recognition', daemon=True)
                                     if self.recognize else None)
            if self._analysis_thread:
                self._analysis_thread.start()
            self._capture_thread.start()
            return self._snapshot_locked()

    def stop(self) -> dict:
        self._stop.set()
        with self._lock:
            process = self._process
            if self._state['running']:
                self._state['phase'] = 'stopping'
            state = self._snapshot_locked()
        if process is not None and process.poll() is None:
            process.terminate()
        return state

    def close(self) -> None:
        self.stop()
        for thread in (self._capture_thread, self._analysis_thread):
            if thread is not None:
                thread.join(timeout=5)

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    def _save_history(self) -> None:
        if self.store is None:
            return
        with self._persist_lock:
            with self._lock:
                snapshot = [dict(item) for item in self._history]
            try:
                self.store.set('guide_demo_history', snapshot)
            except sqlite3.Error:
                self._set(error='本机拍照记录保存失败')

    def _update_entry(self, filename: str, **changes) -> None:
        with self._lock:
            for item in reversed(self._history):
                if item['filename'] == filename:
                    item.update(changes)
                    break
            else:
                return
        self._save_history()

    def _finalize(self) -> None:
        with self._lock:
            if self._capture_done.is_set() and self._analysis_done.is_set():
                self._state.update(running=False, phase='idle')
            elif self._capture_done.is_set():
                self._state['phase'] = 'stopping' if self._stop.is_set() else 'analyzing'

    def _capture(self) -> tuple[Path, float, float]:
        if self._stop.is_set():
            raise InterruptedError
        name = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-glasses.jpg'
        target = self.directory / name
        env = dict(os.environ, LUMA_UNIT=self.unit)
        started_at = time.time()
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
        return photo_path(self.directory, name), time.monotonic() - started, started_at

    def _run_capture(self) -> None:
        errors = 0
        try:
            while not self._stop.is_set():
                try:
                    self._set(phase='capturing', error=None)
                    path, seconds, started_at = self._capture()
                    captured_at = path.stat().st_mtime
                    with self._lock:
                        self._state.update(filename=path.name, captured_at=captured_at,
                                           capture_seconds=round(seconds, 1),
                                           direction='unknown', description='',
                                           sequence=self._state['sequence'] + 1,
                                           captured_count=self._state['captured_count'] + 1)
                        self._history.append({
                            'filename': path.name, 'captured_at': captured_at,
                            'capture_started_at': started_at,
                            'capture_seconds': round(seconds, 1),
                            'analysis_started_at': None, 'analyzed_at': None,
                            'analysis_seconds': None, 'direction': 'unknown',
                            'vision_direction': 'unknown', 'vision_confidence': 0.0,
                            'jev_status': 'pending', 'jev_backend': 'none',
                            'jev_confidence': 0.0, 'jev_seconds': None,
                            'description': '', 'annotations': [], 'error': None,
                            'state': 'queued' if self.recognize else 'complete'})
                    self._save_history()
                    if self.recognize:
                        self._queue.put(path.name)
                    errors = 0
                except InterruptedError:
                    break
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    if self._stop.is_set():
                        break
                    errors += 1
                    self._set(phase='error', error=str(error))
                if self.status()['captured_count'] >= self.max_frames or errors >= 3:
                    break
                self._stop.wait(max(self.pause_seconds, 15 if errors else 0))
        finally:
            self._capture_done.set()
            self._finalize()

    def _run_analysis(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    filename = self._queue.get(timeout=.2)
                except queue.Empty:
                    if self._capture_done.is_set():
                        break
                    continue
                try:
                    if self._stop.is_set():
                        self._update_entry(filename, state='interrupted')
                        break
                    started_at = time.time()
                    started = time.monotonic()
                    self._update_entry(filename, state='analyzing',
                                       analysis_started_at=started_at)
                    try:
                        path = photo_path(self.directory, filename)
                        vision = analyze_demo_jpeg(path.read_bytes())
                        decision = decide_visual_cue(vision)
                        seconds = round(time.monotonic() - started, 1)
                        self._update_entry(filename, state='complete',
                                           direction=decision['direction'],
                                           vision_direction=vision['direction'],
                                           vision_confidence=vision.get('confidence', 0.0),
                                           jev_status=decision['jev_status'],
                                           jev_backend=decision['jev_backend'],
                                           jev_confidence=decision['jev_confidence'],
                                           jev_seconds=decision['jev_seconds'],
                                           description=vision['description'],
                                           annotations=vision.get('annotations', []),
                                           analysis_seconds=seconds, analyzed_at=time.time())
                        self._set(direction=decision['direction'],
                                  description=vision['description'],
                                  analysis_seconds=seconds)
                    except (OSError, ValueError) as error:
                        self._update_entry(filename, state='error', error=str(error),
                                           analyzed_at=time.time())
                finally:
                    self._queue.task_done()
        finally:
            while True:
                try:
                    filename = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._update_entry(filename, state='interrupted')
                self._queue.task_done()
            self._analysis_done.set()
            self._finalize()
