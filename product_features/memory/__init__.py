"""Personal notes and versioned preferences; never apply parameters to a device."""
import json
import math
import time


def clean_text(data, key, limit):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{key} 内容过长或格式不正确')
    return value.strip()


def register(app):
    store = app.ctx.store

    def read(_):
        with store.connect() as db:
            versions = [{'version': r[0], 'created_at': r[1], **json.loads(r[2])}
                        for r in db.execute('SELECT id, created, payload FROM revisions ORDER BY id DESC')]
        return {'profile': store.get('personal_profile', {'name': '', 'goal': 'hiking', 'notes': ''}),
                'versions': versions}

    def profile(data):
        goal = data.get('goal', 'hiking')
        if goal not in {'hiking', 'training', 'both'}: raise ValueError('请选择运动目标')
        value = {'name': clean_text(data, 'name', 40), 'goal': goal, 'notes': clean_text(data, 'notes', 2000)}
        store.set('personal_profile', value)
        return {'profile': value}

    def save_version(data):
        mode = data.get('mode')
        if mode not in {'assist', 'resist'}: raise ValueError('请选择助力或锻炼')
        gain, limit = float(data['gain']), float(data['max_torque'])
        gain_cap, torque_cap = (.2, .8) if mode == 'assist' else (1.0, 1.5)
        if not (math.isfinite(gain) and math.isfinite(limit) and 0 <= gain <= gain_cap and 0 < limit <= torque_cap):
            raise ValueError('参数超出当前产品可保存的范围')
        payload = {'mode': mode, 'gain': gain, 'max_torque': limit,
                   'note': clean_text(data, 'note', 500), 'source': 'user_saved'}
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT id, payload FROM revisions ORDER BY id DESC LIMIT 1').fetchone()
            if previous and json.loads(previous[1]) == payload:
                return {'version': previous[0], 'added': False}
            cursor = db.execute('INSERT INTO revisions(created, payload) VALUES (?, ?)',
                                (time.time(), json.dumps(payload, ensure_ascii=False)))
            return {'version': cursor.lastrowid, 'added': True}

    app.route('GET', '/api/memory/profile', read)
    app.route('POST', '/api/memory/profile', profile)
    app.route('POST', '/api/memory/versions', save_version)
    app.route('GET', '/api/memory/export', lambda _: {'schema_version': 1, **read({}), 'sessions': store.sessions()})
    return {'title': '我的 Ghost', 'description': '记住你的偏好，保存每一次参数调整。', 'order': 30}
