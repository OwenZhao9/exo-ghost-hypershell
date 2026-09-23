import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from product.server import App, Context
from product.storage import Store


def test_worktree_databases_are_isolated(tmp_path):
    a, b = Store(tmp_path / 'a/product.db'), Store(tmp_path / 'b/product.db')
    a.set('profile', {'name': 'A'})
    assert b.get('profile') is None
    assert a.add_session({'id': 'one', 'started_at': 1})
    assert not a.add_session({'id': 'one', 'started_at': 1})
    assert len(a.sessions()) == 1 and b.sessions() == []


def test_http_boundary_and_write_token(tmp_path):
    app = App(Context(Store(tmp_path / 'product.db'), tmp_path))
    app.route('POST', '/api/example', lambda data: data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    root = f'http://127.0.0.1:{server.server_port}'
    try:
        config = json.load(urlopen(root + '/api/config'))
        assert config['control_enabled'] is False and config['device_ws'] is None
        with pytest.raises(HTTPError) as error:
            urlopen(Request(root + '/api/example', data=b'{}'))
        assert error.value.code == 403
        result = json.load(urlopen(Request(root + '/api/example', data=b'{"n":1}',
                              headers={'X-Product-Token': config['token']})))
        assert result == {'n': 1}
        for path in ['/../product/server.py', '/api/missing', '/data/product.db']:
            with pytest.raises(HTTPError) as error:
                urlopen(root + path)
            assert error.value.code == 404
    finally:
        server.shutdown(); server.server_close(); thread.join()
