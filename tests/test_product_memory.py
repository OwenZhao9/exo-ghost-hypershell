import pytest

from product.server import App, Context
from product.storage import Store
from product_features.memory import register


def test_preferences_and_versions_survive_restart(tmp_path):
    store = Store(tmp_path / 'db')
    app = App(Context(store, tmp_path)); register(app)
    profile = {'name': 'Owen', 'goal': 'both', 'notes': '轻一点'}
    app.routes['POST', '/api/memory/profile'](profile)
    save = app.routes['POST', '/api/memory/versions']
    params = {'mode': 'assist', 'gain': .1, 'max_torque': .5, 'note': '公园'}
    assert save(params) == {'version': 1, 'added': True}
    assert save(params) == {'version': 1, 'added': False}
    assert save({**params, 'gain': .2})['version'] == 2
    restarted = App(Context(Store(tmp_path / 'db'), tmp_path)); register(restarted)
    result = restarted.routes['GET', '/api/memory/profile']({})
    assert result['profile'] == profile and len(result['versions']) == 2
    for value in [float('nan'), float('inf'), -.1, 7.5]:
        with pytest.raises(ValueError): save({**params, 'max_torque': value})
    assert len(restarted.routes['GET', '/api/memory/profile']({})['versions']) == 2
