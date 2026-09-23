from .rules import progress


def register(app):
    app.route('GET', '/api/growth/progress', lambda _: progress(app.ctx.store.sessions()))
    return {'title': '成长徽章', 'description': '从真实运动记录中，积累属于自己的里程碑。', 'order': 40}
