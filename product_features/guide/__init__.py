"""Manual photo description from the existing Luma glasses capture directory."""
from __future__ import annotations

import os
import time

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

    app.route('GET', '/api/guide/photos', photos)
    app.route('POST', '/api/guide/describe', describe)
    return {'title': '眼镜看一看', 'description': '选择眼镜拍到的照片，获取画面描述。', 'order': 50}
