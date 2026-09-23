import io
import json
import base64
import time
from urllib.error import HTTPError

import pytest

from product.server import App, Context
from product.storage import Store
from product_features.guide import register
from product_features.guide.vision import ENDPOINT, MODEL, analyze_demo_jpeg, describe_jpeg, photo_path
from product_features.guide.demo import DemoCapture

JPEG = b'\xff\xd8\xff\xe0camera-frame\xff\xd9'


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_named_capture_is_selected_explicitly_and_never_controls_device(tmp_path, monkeypatch):
    shots = tmp_path / 'shots'
    shots.mkdir()
    (shots / 'from-glasses.jpg').write_bytes(JPEG)
    (shots / 'not-a-photo.txt').write_text('private')
    monkeypatch.setenv('EVOMAP_GATEWAY_API_KEY', 'test-key')
    app = App(Context(Store(tmp_path / 'product.db'), tmp_path, glasses_dir=shots))
    register(app)

    photos = app.routes['GET', '/api/guide/photos']({})
    assert [item['filename'] for item in photos['photos']] == ['from-glasses.jpg']
    assert ('POST', '/api/guide/describe') in app.routes
    assert all('policy' not in path for _, path in app.routes)
    assert app.ctx.control is False

    captured = []

    def fake_describe(jpeg):
        captured.append(jpeg)
        return '画面里有一张桌子。'

    monkeypatch.setattr('product_features.guide.describe_jpeg', fake_describe)
    result = app.routes['POST', '/api/guide/describe']({'filename': 'from-glasses.jpg'})
    assert result['description'] == '画面里有一张桌子。'
    assert captured == [JPEG]


def test_capture_cannot_escape_directory(tmp_path):
    shots = tmp_path / 'shots'
    shots.mkdir()
    (tmp_path / 'secret.jpg').write_bytes(JPEG)
    (shots / 'link.jpg').symlink_to(tmp_path / 'secret.jpg')
    for name in ['../secret.jpg', 'link.jpg', '/tmp/secret.jpg', 'secret.png']:
        with pytest.raises(ValueError):
            photo_path(shots, name)


def test_latest_photo_is_displayed_locally_without_gateway_upload(tmp_path):
    shots = tmp_path / 'shots'
    shots.mkdir()
    (shots / 'new.jpg').write_bytes(JPEG)
    app = App(Context(Store(tmp_path / 'product.db'), tmp_path, glasses_dir=shots))
    register(app)
    result = app.routes['GET', '/api/guide/latest']({})['photo']
    assert result['filename'] == 'new.jpg'
    assert base64.b64decode(result['src'].split(',', 1)[1]) == JPEG
    assert app.routes['GET', '/api/guide/demo']({}) == {'available': False}


def test_demo_capture_pins_unit_and_stops_without_upload(tmp_path):
    shots = tmp_path / 'shots'
    shots.mkdir()
    fake = tmp_path / 'luma'
    fake.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
assert os.environ['LUMA_UNIT'] == 'E06-0194'
assert sys.argv[1:3] == ['photo', '--ai']
pathlib.Path(sys.argv[3]).write_bytes(b'\\xff\\xd8\\xff\\xe0photo\\xff\\xd9')
''')
    fake.chmod(0o700)
    demo = DemoCapture(fake, shots, 'E06-0194', recognize=False)
    demo.start()
    until = time.monotonic() + 5
    while demo.status()['sequence'] < 1 and time.monotonic() < until:
        time.sleep(.02)
    demo.stop()
    demo.close()
    state = demo.status()
    assert state['sequence'] >= 1
    assert state['direction'] == 'unknown'
    assert (shots / state['filename']).is_file()


def test_demo_direction_falls_back_when_uncertain():
    def reply(value, fenced=False):
        content = json.dumps(value)
        if fenced:
            content = f'```json\n{content}\n```'
        return lambda request, timeout: Reply(json.dumps({
            'choices': [{'message': {'content': content}}]}).encode())

    assert analyze_demo_jpeg(JPEG, key='test-key', opener=reply({
        'direction': 'left', 'confidence': .95, 'description': '画面模糊，左侧似乎空旷。'
    }))['direction'] == 'unknown'
    assert analyze_demo_jpeg(JPEG, key='test-key', opener=reply({
        'direction': 'right', 'confidence': .9, 'description': '画面左边有箱子，右边地面可见。'
    }, fenced=True))['direction'] == 'right'


def test_gateway_request_contains_image_and_keeps_key_out_of_body():
    seen = []

    def opener(request, timeout):
        seen.append((request, timeout))
        return Reply(json.dumps({'choices': [{'message': {'content': '画面里有台阶。'}}]}).encode())

    text = describe_jpeg(JPEG, key='test-key', opener=opener)
    request, timeout = seen[0]
    body = json.loads(request.data)
    assert text == '画面里有台阶。'
    assert request.full_url == ENDPOINT and timeout == 75
    assert request.get_header('Authorization') == 'Bearer test-key'
    assert body['model'] == MODEL
    assert body['reasoning_effort'] == 'low' and body['max_tokens'] == 2048
    assert body['messages'][0]['role'] == 'system'
    assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert b'test-key' not in request.data


def test_gateway_failure_does_not_expose_key():
    def opener(request, timeout):
        raise HTTPError(ENDPOINT, 401, 'bad key', {}, None)

    with pytest.raises(ValueError, match='鉴权或模型权限') as error:
        describe_jpeg(JPEG, key='secret-key', opener=opener)
    assert 'secret-key' not in str(error.value)


def test_upstream_rate_limit_is_reported_as_model_busy():
    def opener(request, timeout):
        raise HTTPError(ENDPOINT, 429, 'provider overloaded', {}, None)

    with pytest.raises(ValueError, match='模型服务暂时繁忙'):
        describe_jpeg(JPEG, key='test-key', opener=opener)
