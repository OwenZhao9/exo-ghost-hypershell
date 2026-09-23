from .importer import import_record, source_path, journal_metadata


def register(app):
    def sources(_):
        files = []
        candidates = sorted(app.ctx.recordings.glob('*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in candidates[:500]:
            try:
                path = source_path(app.ctx.recordings, candidate.name)
                start, _ = journal_metadata(path)
                if start.get('body') == 'sim' or path.name.startswith('sim_'):
                    continue
                files.append({'name': path.name, 'bytes': path.stat().st_size})
            except (ValueError, OSError):
                continue
        return {'files': files}

    def receive(data):
        context = data.get('context', {})
        if not isinstance(context, dict): raise ValueError('记录信息格式不正确')
        record = import_record(app.ctx.recordings, data['filename'], context)
        if record['body'] == 'sim' or record['source_file'].startswith('sim_'):
            raise ValueError('产品档案只收录设备记录')
        added = app.ctx.store.add_session(record)
        return {'added': added, 'session': record}

    app.route('GET', '/api/records/sources', sources)
    app.route('POST', '/api/records/import', receive)
    return {'title': '行走档案', 'description': '回看每次运动，观察左右腿的运动变化。', 'order': 20}
