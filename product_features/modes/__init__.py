"""Product presets use the existing runtime policy and safety gates."""

PRESETS = [
    {'id': 'assist', 'title': '户外助力', 'description': '顺着你的动作提供轻量辅助。',
     'levels': [{'name': '轻量', 'gain': .1, 'max': .5}, {'name': '适中', 'gain': .2, 'max': .8}]},
    {'id': 'resist', 'title': '阻力锻炼', 'description': '通过可控阻力，记录左右腿的运动表现。',
     'levels': [{'name': '轻量', 'gain': .3, 'max': .5}, {'name': '适中', 'gain': .5, 'max': 1.0}]},
]


def register(app):
    app.route('GET', '/api/modes/presets', lambda _: {'presets': PRESETS})
    return {'title': '运动模式', 'description': '选择助力或锻炼，查看当前运动曲线。', 'order': 10}
