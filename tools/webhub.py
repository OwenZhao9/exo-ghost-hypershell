"""WebSocket 广播 + 静态页面服务器，供仪表盘/手机控制台使用。
在服务里：hub = WebHub(on_command); hub.start(); hub.push_sample(...); hub.push_status(...); hub.push_event(...)
"""
from __future__ import annotations
import asyncio, http.server, json, os, socket, threading, time
from typing import Callable, Optional
import websockets

DASH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()


class WebHub:
    def __init__(self, on_command: Callable[[dict], None], ws_port: int = 8765, http_port: int = 8000,
                 sample_div: int = 3, ws_host: str = "0.0.0.0"):
        self.on_command = on_command
        self.ws_port, self.http_port, self.sample_div = ws_port, http_port, sample_div
        self.ws_host = ws_host
        self._clients: set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._n = 0
        self._last_status: Optional[dict] = None
        self._events: list[dict] = []

    # ---------- 生命周期 ----------
    def start(self) -> None:
        threading.Thread(target=self._run_ws, name="webhub-ws", daemon=True).start()
        threading.Thread(target=self._run_http, name="webhub-http", daemon=True).start()

    def _run_http(self) -> None:
        handler = lambda *a, **k: _Quiet(*a, directory=DASH_DIR, **k)
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        try:
            srv = http.server.ThreadingHTTPServer(("0.0.0.0", self.http_port), handler)
        except OSError as e:
            print(f"!!! 仪表盘 HTTP 端口 {self.http_port} 启动失败：{e}", flush=True); return
        srv.serve_forever()

    def _run_ws(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        async def main():
            try:
                async with websockets.serve(self._handler, self.ws_host, self.ws_port, max_queue=64, ping_interval=10, ping_timeout=10):
                    await asyncio.Future()
            except OSError as e:
                print(f"!!! WebSocket 端口 {self.ws_port} 启动失败：{e}（被别的程序占用？）", flush=True)
        self._loop.run_until_complete(main())

    async def _handler(self, ws):
        self._clients.add(ws)
        try:
            if self._last_status: await ws.send(json.dumps({"k": "st", **self._last_status}))
            for ev in self._events[-30:]: await ws.send(json.dumps(ev))
            async for msg in ws:
                try:
                    c = json.loads(msg)
                except Exception:
                    continue
                if isinstance(c, dict) and "op" in c:
                    self.on_command(c)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    # ---------- 广播 ----------
    def _broadcast(self, text: str) -> None:
        if not self._loop or not self._clients: return
        def _send():
            for ws in list(self._clients):
                try:
                    asyncio.ensure_future(ws.send(text))
                except Exception:
                    self._clients.discard(ws)
        try:
            self._loop.call_soon_threadsafe(_send)
        except Exception:
            pass

    def push_sample(self, s, tau_l: float, tau_r: float, scale: float) -> None:
        self._n += 1
        if self._n % self.sample_div: return
        v = [round(s.ldeg, 2), round(s.rdeg, 2), round(s.ldps, 1), round(s.rdps, 1), round(tau_l, 3), round(tau_r, 3), round(scale, 2),
             round(s.pitch, 1), round(s.roll, 1), round(s.yaw, 1), round(s.gx, 1), round(s.gy, 1), round(s.gz, 1),
             round(s.ax, 3), round(s.ay, 3), round(s.az, 3), round(s.kpa, 3), s.ms]
        self._broadcast(json.dumps({"k": "s", "t": round(s.host_t, 3), "v": v}))

    def push_status(self, st: dict) -> None:
        self._last_status = st
        self._broadcast(json.dumps({"k": "st", **st}))

    def push_event(self, msg: str, level: str = "info") -> None:
        ev = {"k": "ev", "t": time.time(), "msg": msg, "level": level}
        self._events.append(ev); self._events = self._events[-200:]
        self._broadcast(json.dumps(ev))

    @property
    def n_clients(self) -> int:
        return len(self._clients)


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"
