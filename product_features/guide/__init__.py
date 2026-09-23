"""Manual photo description from the existing Luma glasses capture directory."""
from __future__ import annotations

import os
import time
import base64

from .vision import KEY_ENV, describe_jpeg, photo_path, recent_photos


def register(app):
    directory = app.ctx.glasses_dir

    def photos(_):
        return {'photos': recent_photos(directory),
                'capture_available': directory is not None and directory.is_dir(),
                'vision_available': bool(os.environ.get(KEY_ENV))}

    def describe(data):
        if directory is None or not directory.is_dir():
            raise ValueError('尚未连接眼镜照片目录')
        filename = data.get('filename')
        if not isinstance(filename, str):
            raise ValueError('请选择一张眼镜照片')
        path = photo_path(directory, filename)
        captured_at = path.stat().st_mtime
        description = describe_jpeg(path.read_bytes())
        return {'description': description, 'filename': filename,
                'captured_at': captured_at, 'described_at': time.time(),
                'historical': time.time() - captured_at > 30}

    def latest(_):
        recent = recent_photos(directory, limit=1)
        if not recent:
            return {'photo': None}
        item = recent[0]
        path = photo_path(directory, item['filename'])
        return {'photo': {**item, 'src': 'data:image/jpeg;base64,' +
                base64.b64encode(path.read_bytes()).decode('ascii')}}

    def demo_status(_):
        demo = app.ctx.guide_demo
        return {'available': demo is not None,
                **(demo.status() if demo is not None else {})}

    def demo_start(_):
        demo = app.ctx.guide_demo
        if demo is None:
            raise ValueError('眼镜演示采集尚未配置')
        return {'available': True, **demo.start()}

    def demo_stop(_):
        demo = app.ctx.guide_demo
        if demo is None:
            raise ValueError('眼镜演示采集尚未配置')
        return {'available': True, **demo.stop()}

    app.route('GET', '/api/guide/photos', photos)
    app.route('GET', '/api/guide/latest', latest)
    app.route('POST', '/api/guide/describe', describe)
    app.route('GET', '/api/guide/demo', demo_status)
    app.route('POST', '/api/guide/demo/start', demo_start)
    app.route('POST', '/api/guide/demo/stop', demo_stop)
    return {'title': '眼镜看一看', 'description': '查看眼镜照片，并在本机启动拍照演示。', 'order': 50}
