import io
import json
import base64
import threading
import time
import wave
from pathlib import Path
from urllib.error import HTTPError

import pytest

from product.server import App, Context
from product.storage import Store
from product_features.guide import register
from product_features.guide.vision import ENDPOINT, MODEL, analyze_demo_jpeg, describe_jpeg, photo_path
from product_features.guide.demo import DemoCapture

JPEG = b'\xff\xd8\xff\xe0camera-frame\xff\xd9'


def test_all_voice_cues_are_complete_wav_files():
    audio = Path(__file__).resolve().parents[1] / 'product_features/guide/audio'
    for name in ('left', 'right', 'unknown', 'stop'):
        with wave.open(str(audio / f'{name}.wav'), 'rb') as clip:
            assert clip.getnchannels() == 1
            assert clip.getframerate() == 24000
            assert clip.getnframes() > 12000


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
    image = app.routes['POST', '/api/guide/image']({'filename': 'new.jpg'})
    assert base64.b64decode(image['src'].split(',', 1)[1]) == JPEG
    assert app.routes['GET', '/api/guide/demo']({}) == {'available': False}


def test_demo_capture_appends_results_and_restores_them(tmp_path, monkeypatch):
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
    store = Store(tmp_path / 'product.db')
    decisions = iter([{'direction': 'left', 'description': '左侧可见空地。'},
                      {'direction': 'right', 'description': '右侧可见空地。'}])
    monkeypatch.setattr('product_features.guide.demo.analyze_demo_jpeg', lambda _: next(decisions))
    demo = DemoCapture(fake, shots, 'E06-0194', recognize=True,
                       pause_seconds=2, max_frames=2, store=store)
    demo.start()
    until = time.monotonic() + 6
    while (len(demo.status()['history']) < 2 or demo.status()['running']) and time.monotonic() < until:
        time.sleep(.02)
    demo.stop()
    demo.close()
    state = demo.status()
    assert state['captured_count'] == 2
    assert [item['direction'] for item in state['history']] == ['left', 'right']
    assert [item['description'] for item in state['history']] == ['左侧可见空地。', '右侧可见空地。']
    assert all((shots / item['filename']).is_file() for item in state['history'])
    restored = DemoCapture(fake, shots, 'E06-0194', recognize=False, store=store)
    assert restored.status()['history'] == state['history']


def test_capture_overlaps_previous_photo_recognition(tmp_path, monkeypatch):
    shots = tmp_path / 'shots'
    shots.mkdir()
    fake = tmp_path / 'luma'
    fake.write_text('''#!/usr/bin/env python3
import pathlib, sys, time
time.sleep(.12)
pathlib.Path(sys.argv[3]).write_bytes(b'\\xff\\xd8\\xff\\xe0photo\\xff\\xd9')
''')
    fake.chmod(0o700)

    def analyze(_):
        time.sleep(.55)
        return {'direction': 'unknown', 'description': '画面较暗。',
                'annotations': [{'label': '桌子', 'box': [.2, .3, .4, .2]}]}

    monkeypatch.setattr('product_features.guide.demo.analyze_demo_jpeg', analyze)
    demo = DemoCapture(fake, shots, 'E06-0194', recognize=True,
                       pause_seconds=.02, max_frames=2)
    demo.start()
    until = time.monotonic() + 5
    while demo.status()['running'] and time.monotonic() < until:
        time.sleep(.02)
    history = demo.status()['history']
    assert len(history) == 2
    assert history[0]['analysis_started_at'] < history[1]['captured_at']
    assert history[1]['capture_started_at'] < history[0]['analyzed_at']
    assert all(item['state'] == 'complete' for item in history)
    assert history[0]['annotations'][0]['label'] == '桌子'
    demo.close()


def test_stop_skips_photos_not_yet_sent_for_recognition(tmp_path, monkeypatch):
    shots = tmp_path / 'shots'
    shots.mkdir()
    fake = tmp_path / 'luma'
    fake.write_text('''#!/usr/bin/env python3
import pathlib, sys
pathlib.Path(sys.argv[3]).write_bytes(b'\\xff\\xd8\\xff\\xe0photo\\xff\\xd9')
''')
    fake.chmod(0o700)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def analyze(_):
        calls.append(1)
        entered.set()
        release.wait(3)
        return {'direction': 'unknown', 'description': '画面较暗。', 'annotations': []}

    monkeypatch.setattr('product_features.guide.demo.analyze_demo_jpeg', analyze)
    demo = DemoCapture(fake, shots, 'E06-0194', recognize=True,
                       pause_seconds=0, max_frames=3)
    demo.start()
    until = time.monotonic() + 5
    while (len(demo.status()['history']) < 3 or not entered.is_set()) and time.monotonic() < until:
        time.sleep(.02)
    assert len(demo.status()['history']) == 3
    demo.stop()
    release.set()
    demo.close()
    assert calls == [1]
    assert [item['state'] for item in demo.status()['history']] == [
        'complete', 'interrupted', 'interrupted']


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
    annotated = analyze_demo_jpeg(JPEG, key='test-key', opener=reply({
        'direction': 'unknown', 'confidence': 0, 'description': '画面里有一张桌子。',
        'annotations': [{'label': '桌子', 'box': [.1, .2, .3, .4]},
                        {'label': '越界', 'box': [.9, .2, .3, .4]}]
    }))
    assert annotated['annotations'] == [{'label': '桌子', 'box': [.1, .2, .3, .4]}]


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
