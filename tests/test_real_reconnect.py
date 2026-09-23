"""真机串口恢复路径：用假的串口协议验证热插拔，不触碰实际电机。"""
import queue
import threading
import time

import serial

from bridge.exo import ExoBridge
from runtime.status import device_state


class FakeSerial:
    def __init__(self, port, baud, timeout, write_timeout):
        if port == "/dev/old":
            raise serial.SerialException("旧串口已消失")
        self.port = port
        self.is_open = True
        self.lines = queue.Queue()
        self.commands = []

    @property
    def in_waiting(self):
        return 0

    def reset_input_buffer(self):
        pass

    def write(self, data):
        cmd = data.decode().strip()
        self.commands.append(cmd)
        if cmd == "PING":
            self.lines.put(b"PONG\n")
        elif cmd == "VERSION":
            self.lines.put(b"OK,VERSION,test\n")
        elif cmd == "ENABLE":
            self.lines.put(b"OK,ENABLE\n")
        elif cmd == "DISABLE":
            self.lines.put(b"OK,DISABLE\n")

    def read(self, _size):
        try:
            return self.lines.get(timeout=0.02)
        except queue.Empty:
            return b""

    def close(self):
        self.is_open = False


class FastStop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, _seconds):
        return self.stopped


def test_retries_beyond_old_limit_and_connects_changed_port(monkeypatch):
    import bridge.exo as exo

    scans = 0
    opened = []

    def candidates(_preferred):
        nonlocal scans
        scans += 1
        return [] if scans <= 45 else ["/dev/old", "/dev/new"]

    def serial_factory(*args, **kwargs):
        s = FakeSerial(*args, **kwargs)
        opened.append(s)
        return s

    monkeypatch.setattr(exo, "port_candidates", candidates)
    monkeypatch.setattr(exo.serial, "Serial", serial_factory)
    bridge = ExoBridge(port="/dev/old", log_dir=None)
    bridge._stop = FastStop()
    events = []
    bridge.on_event(events.append)
    bridge.set_torque(1.0, 1.0)
    try:
        bridge._reconnect()
        assert scans == 46
        assert bridge.port == "/dev/new"
        assert bridge.enabled and not bridge._reconnecting
        assert bridge.n_reconnects == 1
        assert bridge._target == bridge.commanded == (0.0, 0.0)
        assert opened[0].commands[:3] == ["PING", "VERSION", "ENABLE"]
        assert events == ["stall", "reconnected"]
    finally:
        bridge.close()


def test_waiting_for_port_can_be_stopped(monkeypatch):
    import bridge.exo as exo

    monkeypatch.setattr(exo, "port_candidates", lambda _preferred: [])
    bridge = ExoBridge(log_dir=None)
    bridge.start_recovery(send_torque=True)
    deadline = time.time() + 1
    while not bridge._reconnecting and time.time() < deadline:
        time.sleep(0.005)
    assert bridge._reconnecting
    bridge.close()
    bridge._recovery_thread.join(timeout=1)
    assert not bridge._recovery_thread.is_alive()
    assert not bridge.enabled


def test_disconnected_and_quiet_states_are_not_running():
    common = dict(tripped=None, armed=True, legs_offline=False, reconnecting=False)
    assert device_state(**common, connected=False) == "RECONN"
    assert device_state(**common, connected=True, quiet=True) == "QUIET"


def test_startup_without_port_still_recovers_after_later_disconnect(monkeypatch):
    import bridge.exo as exo

    available = []
    connected = threading.Event()
    monkeypatch.setattr(exo, "port_candidates", lambda _preferred: list(available))
    monkeypatch.setattr(exo.serial, "Serial", FakeSerial)
    bridge = ExoBridge(log_dir=None)
    bridge.on_event(lambda event: connected.set() if event == "reconnected" else None)
    try:
        bridge.start_recovery(send_torque=False)
        assert not connected.wait(timeout=0.05)
        available[:] = ["/dev/first"]
        assert connected.wait(timeout=2), "首次插入后应自动连接"
        assert bridge.port == "/dev/first"
        assert bridge._supervisor and bridge._supervisor.is_alive()

        connected.clear()
        available[:] = ["/dev/second"]
        bridge.last_sample_t = time.time() - 10
        bridge._enabled_at = time.time() - 10
        assert connected.wait(timeout=2), "首次晚连接之后，后续断线仍应有人监测并恢复"
        assert bridge.port == "/dev/second"
        assert bridge.n_reconnects == 2
        assert bridge._target == bridge.commanded == (0.0, 0.0)
    finally:
        bridge.close()
        if bridge._supervisor:
            bridge._supervisor.join(timeout=2)
