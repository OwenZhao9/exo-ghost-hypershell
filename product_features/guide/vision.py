"""Explicit, one-shot image description through the EvoMap Gateway.

No camera, serial, or actuator I/O happens in this module. Photos leave the
computer only when the local user requests a description of a named capture.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.evomap.ai/v1/chat/completions'
MODEL = 'evomap-gemini-3.1-pro-preview'
KEY_ENV = 'EVOMAP_GATEWAY_API_KEY'
MAX_JPEG_BYTES = 5 * 1024 * 1024

PROMPT = (
    '请用简体中文简短描述这张照片中能直接看见的环境，以及可能影响行走的物体。'
    '只描述画面中的事实；不确定时明确说不确定。不要声称路线安全、可通行，'
    '不要给出移动方向、距离或外骨骼控制指令。'
)


def photo_path(directory: Path, filename: str) -> Path:
    if not filename or filename != Path(filename).name or '/' in filename or '\\' in filename:
        raise ValueError('照片名称无效')
    if Path(filename).suffix.lower() not in {'.jpg', '.jpeg'}:
        raise ValueError('只能识别 JPEG 照片')
    root = directory.resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('照片不存在')
    if not 0 < path.stat().st_size <= MAX_JPEG_BYTES:
        raise ValueError('照片大小不在允许范围内')
    return path


def recent_photos(directory: Path | None, limit: int = 12) -> list[dict]:
    if directory is None or not directory.is_dir():
        return []
    root = directory.resolve()
    files = []
    for path in root.iterdir():
        try:
            if path.suffix.lower() not in {'.jpg', '.jpeg'}:
                continue
            checked = photo_path(root, path.name)
            stat = checked.stat()
            files.append({'filename': path.name, 'captured_at': stat.st_mtime,
                          'size_bytes': stat.st_size})
        except (OSError, ValueError):
            continue
    files.sort(key=lambda item: item['captured_at'], reverse=True)
    return files[:limit]


def describe_jpeg(jpeg: bytes, *, key: str | None = None, opener=urlopen) -> str:
    if not jpeg.startswith(b'\xff\xd8\xff') or not jpeg.rstrip().endswith(b'\xff\xd9'):
        raise ValueError('照片不是完整的 JPEG')
    if not 0 < len(jpeg) <= MAX_JPEG_BYTES:
        raise ValueError('照片大小不在允许范围内')
    key = key or os.environ.get(KEY_ENV, '')
    if not key:
        raise ValueError('尚未配置 EvoMap Gateway Key')
    image = base64.b64encode(jpeg).decode('ascii')
    body = json.dumps({
        'model': MODEL,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': PROMPT},
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image}'}},
        ]}],
        'max_tokens': 220,
    }, ensure_ascii=False).encode('utf-8')
    request = Request(ENDPOINT, data=body, headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
    }, method='POST')
    try:
        with opener(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise ValueError('EvoMap 鉴权或模型权限失败，请检查 Gateway Key 和模型绑定') from None
        if error.code == 429:
            raise ValueError('EvoMap 模型服务暂时繁忙，请稍后再试') from None
        raise ValueError(f'EvoMap 请求失败（HTTP {error.code}）') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('EvoMap 暂时无法连接或请求超时') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('EvoMap 返回格式异常，请稍后再试') from None
    try:
        content = result['choices'][0]['message']['content']
        if isinstance(content, list):
            content = ' '.join(part.get('text', '') for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        return content.strip()[:1200]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('EvoMap 没有返回可用的文字描述') from None
