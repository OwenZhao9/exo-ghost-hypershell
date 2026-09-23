import io
import json
from urllib.error import HTTPError

import pytest

from product.server import App, Context
from product.storage import Store
from product_features.guide import register
from product_features.guide.vision import ENDPOINT, MODEL, describe_jpeg, photo_path

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


def test_gateway_request_contains_image_and_keeps_key_out_of_body():
    seen = []

    def opener(request, timeout):
        seen.append((request, timeout))
        return Reply(json.dumps({'choices': [{'message': {'content': '画面里有台阶。'}}]}).encode())

    text = describe_jpeg(JPEG, key='test-key', opener=opener)
    request, timeout = seen[0]
    body = json.loads(request.data)
    assert text == '画面里有台阶。'
    assert request.full_url == ENDPOINT and timeout == 60
    assert request.get_header('Authorization') == 'Bearer test-key'
    assert body['model'] == MODEL
    assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
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
