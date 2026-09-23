"""Local product HTTP service. Never opens a serial port or starts a body."""
from __future__ import annotations

import argparse
import importlib
import json
import mimetypes
import pkgutil
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .storage import Store
from .workspace import default_port

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Context:
    store: Store
    recordings: Path
    device_ws: str | None = None
    control: bool = False
    glasses_dir: Path | None = None
    guide_demo: object | None = None


class App:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.routes = {}
        self.features = []
        self.static = {'/': ROOT / 'dashboard/product'}
        self.token = secrets.token_urlsafe(32)
        self.route('GET', '/api/config', lambda _: {
            'schema_version': 1, 'features': self.features, 'token': self.token,
            'device_ws': ctx.device_ws, 'control_enabled': ctx.control})
        self.route('GET', '/api/sessions', lambda _: {'sessions': ctx.store.sessions()})

    def route(self, method, path, handler):
        key = (method, path)
        if key in self.routes:
            raise ValueError(f'Duplicate route: {method} {path}')
        self.routes[key] = handler

    def discover(self):
        import product_features
        for item in sorted(pkgutil.iter_modules(product_features.__path__), key=lambda i: i.name):
            module = importlib.import_module(f'product_features.{item.name}')
            if not hasattr(module, 'register'):
                continue
            feature = module.register(self)
            feature['id'] = item.name
            feature['module'] = f'/features/{item.name}/view.js'
            self.features.append(feature)
            self.static[f'/features/{item.name}/'] = Path(module.__file__).parent
        self.features.sort(key=lambda item: item.get('order', 100))

    def handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def send_body(self, status, data, kind='application/json; charset=utf-8'):
                if not isinstance(data, bytes):
                    data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(data)

            def handle_request(self):
                path = urlsplit(self.path).path
                callback = app.routes.get((self.command, path))
                if callback:
                    try:
                        payload = {}
                        if self.command == 'POST':
                            if not secrets.compare_digest(self.headers.get('X-Product-Token', ''), app.token):
                                self.send_body(403, {'error': '请刷新页面后重试'})
                                return
                            length = int(self.headers.get('Content-Length', 0))
                            if not 0 < length <= 65536:
                                raise ValueError('请求大小不正确')
                            payload = json.loads(self.rfile.read(length))
                            if not isinstance(payload, dict):
                                raise ValueError('请求需要是一个对象')
                        self.send_body(200, callback(payload))
                    except (ValueError, KeyError, TypeError) as e:
                        self.send_body(400, {'error': str(e)})
                    except Exception as e:
                        print(f'Product request failed: {path}: {e}', flush=True)
                        self.send_body(500, {'error': '暂时无法处理，请稍后重试'})
                    return
                if self.command != 'GET' or path.startswith('/api/'):
                    self.send_body(404, {'error': '页面不存在'})
                    return
                for prefix, directory in sorted(app.static.items(), key=lambda item: -len(item[0])):
                    if not path.startswith(prefix):
                        continue
                    target = (directory / (path[len(prefix):] or 'index.html')).resolve()
                    # Only serve public assets, never feature Python modules or local data.
                    if (not target.is_relative_to(directory.resolve()) or
                            target.suffix not in {'.html', '.js', '.css', '.svg', '.png', '.webp', '.wav'} or
                            not target.is_file()):
                        break
                    kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                    self.send_body(200, target.read_bytes(), kind)
                    return
                self.send_body(404, {'error': '页面不存在'})

            do_GET = handle_request
            do_POST = handle_request

        return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description='Ghost 产品工作区（不占用串口）')
    ap.add_argument('--port', type=int, default=default_port(ROOT))
    ap.add_argument('--data-dir', type=Path, default=ROOT / 'data/product')
    ap.add_argument('--recordings-dir', type=Path, default=ROOT / 'data')
    ap.add_argument('--device-ws', help='现有控制服务地址，如 ws://127.0.0.1:8765')
    ap.add_argument('--control', action='store_true', help='允许页面向已连接的真机服务发送操作命令')
    ap.add_argument('--glasses-dir', type=Path, help='眼镜采集文件目录（只读）')
    ap.add_argument('--glasses-bin', type=Path, help='启用眼镜演示采集的 Luma 拍照程序')
    ap.add_argument('--glasses-unit', help='当前眼镜 BLE 广播名，例如 E06-0194')
    ap.add_argument('--guide-demo-upload', action='store_true', help='演示期间自动将新照片发送给 EvoMap 分析')
    a = ap.parse_args(argv)
    if a.device_ws:
        url = urlsplit(a.device_ws)
        if url.scheme != 'ws' or url.hostname not in {'localhost', '127.0.0.1', '::1'}:
            ap.error('--device-ws 需要是本机的 ws 地址')
    if a.control and not a.device_ws:
        ap.error('--control 需要同时指定 --device-ws')
    if a.glasses_bin and (not a.glasses_dir or not a.glasses_unit):
        ap.error('--glasses-bin 需要同时指定 --glasses-dir 和 --glasses-unit')
    if a.guide_demo_upload and not a.glasses_bin:
        ap.error('--guide-demo-upload 需要同时指定 --glasses-bin')
    ctx = Context(Store(a.data_dir.resolve() / 'product.db'), a.recordings_dir.resolve(),
                  a.device_ws, a.control, a.glasses_dir.resolve() if a.glasses_dir else None)
    if a.glasses_bin:
        from product_features.guide.demo import DemoCapture
        try:
            ctx.guide_demo = DemoCapture(a.glasses_bin, ctx.glasses_dir,
                                         a.glasses_unit, recognize=a.guide_demo_upload,
                                         store=ctx.store)
        except ValueError as error:
            ap.error(str(error))
    app = App(ctx)
    app.discover()
    server = ThreadingHTTPServer(('127.0.0.1', a.port), app.handler())
    print(f'Ghost 产品工作区：http://localhost:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if ctx.guide_demo:
            ctx.guide_demo.close()
        server.server_close()


if __name__ == '__main__':
    main()
