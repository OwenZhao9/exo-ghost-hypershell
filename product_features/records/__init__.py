from .importer import import_record, source_path


def register(app):
    def sources(_):
        files = []
        for candidate in sorted(app.ctx.recordings.glob('*.csv'), reverse=True)[:500]:
            try:
                path = source_path(app.ctx.recordings, candidate.name)
                files.append({'name': path.name, 'bytes': path.stat().st_size})
            except (ValueError, OSError):
                continue
        return {'files': files}

    def receive(data):
        context = data.get('context', {})
        if not isinstance(context, dict): raise ValueError('记录信息格式不正确')
        record = import_record(app.ctx.recordings, data['filename'], context)
        added = app.ctx.store.add_session(record)
        return {'added': added, 'session': record}

    app.route('GET', '/api/records/sources', sources)
    app.route('POST', '/api/records/import', receive)
    return {'title': '行走档案', 'description': '回看每次运动，观察左右腿的运动变化。', 'order': 20}
