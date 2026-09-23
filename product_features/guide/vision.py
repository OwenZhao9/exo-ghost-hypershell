"""Explicit, one-shot image description through the EvoMap Gateway.

No camera, serial, or actuator I/O happens in this module. Photos leave the
computer only when the local user requests a description of a named capture.
"""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.evomap.ai/v1/chat/completions'
MODEL = 'evomap-gemini-3.1-pro-preview'
KEY_ENV = 'EVOMAP_GATEWAY_API_KEY'
MAX_JPEG_BYTES = 5 * 1024 * 1024

SYSTEM_PROMPT = (
    '你是视觉描述助手。只输出一到两句直接观察到的画面事实。'
    '不要分析指令、列清单、推断安全性或给出行动方向。'
)
PROMPT = '请用简体中文描述这张图中可见的环境与可能影响行走的物体；看不清时直接说看不清。'
DEMO_SYSTEM_PROMPT = (
    '你只分析一张静止照片，供有人看护的桌面演示使用。'
    '只能根据画面中直接可见的物体比较图像左、右两侧，不能判断真实道路是否安全。'
    '画面模糊、地面不可见、被遮挡、两侧相似或缺乏依据时必须给 unknown。'
    '可以标出画面里清楚可见的物体位置；不要猜测看不清的物体。'
    '只输出 JSON 对象，不要包含行动命令或额外文字。'
)
DEMO_PROMPT = (
    '输出 {"direction":"left|right|unknown","confidence":0到1的数字,'
    '"description":"一句简体中文画面事实",'
    '"annotations":[{"label":"可见物体名","box":[x,y,w,h]}]}。'
    'box 是相对整张图的 0 到 1 坐标，左上角为 (0,0)；最多标出 3 个确实可见的物体，'
    '无法确认边界时返回空数组。left/right 只表示画面该侧看起来更空，'
    '不是让人朝该方向行走。不能确认方向时 direction=unknown，confidence=0。'
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


def recent_photos(directory: Path | None, limit: int | None = 12) -> list[dict]:
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


def describe_jpeg(jpeg: bytes, *, key: str | None = None, opener=urlopen,
                  system_prompt: str = SYSTEM_PROMPT, prompt: str = PROMPT,
                  max_tokens: int = 2048) -> str:
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
        'reasoning_effort': 'low',
        'temperature': 0,
        'messages': [{'role': 'system', 'content': system_prompt},
                     {'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image}'}},
        ]}],
        'max_tokens': max_tokens,
    }, ensure_ascii=False).encode('utf-8')
    request = Request(ENDPOINT, data=body, headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
    }, method='POST')
    try:
        with opener(request, timeout=75) as response:
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


def analyze_demo_jpeg(jpeg: bytes, *, key: str | None = None, opener=urlopen) -> dict:
    """Conservative image-side comparison; never a verified walking instruction."""
    raw = describe_jpeg(jpeg, key=key, opener=opener,
                        system_prompt=DEMO_SYSTEM_PROMPT, prompt=DEMO_PROMPT,
                        max_tokens=1024)
    try:
        text = raw.strip()
        if text.startswith('```json\n') and text.endswith('\n```'):
            text = text[len('```json\n'):-len('\n```')]
        value = json.loads(text)
        direction = value['direction']
        confidence = value['confidence']
        description = value['description']
        if (direction not in {'left', 'right', 'unknown'} or
                not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or
                not math.isfinite(confidence) or not 0 <= confidence <= 1 or
                not isinstance(description, str) or
                not 0 < len(description.strip()) <= 240):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        return {'direction': 'unknown', 'confidence': 0.0, 'description': '画面判断不明确。',
                'annotations': []}
    description = description.strip()
    annotations = []
    raw_annotations = value.get('annotations', [])
    if isinstance(raw_annotations, list):
        for item in raw_annotations[:3]:
            if not isinstance(item, dict):
                continue
            label, box = item.get('label'), item.get('box')
            if (not isinstance(label, str) or not 0 < len(label.strip()) <= 20 or
                    not isinstance(box, list) or len(box) != 4 or
                    any(not isinstance(n, (int, float)) or isinstance(n, bool) or
                        not math.isfinite(n) for n in box)):
                continue
            x, y, w, h = box
            if 0 <= x < 1 and 0 <= y < 1 and .03 <= w <= 1 and .03 <= h <= 1 and x + w <= 1 and y + h <= 1:
                annotations.append({'label': label.strip(), 'box': [round(n, 4) for n in box]})
    if (confidence < 0.85 or any(word in description for word in
                                 ('模糊', '看不清', '无法确认', '不清楚', '不确定'))):
        direction = 'unknown'
    return {'direction': direction, 'confidence': confidence if direction != 'unknown' else 0.0,
            'description': description,
            'annotations': annotations}
