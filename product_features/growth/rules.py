"""Achievements derive only from completed real wearing records with movement."""
from datetime import datetime
from zoneinfo import ZoneInfo


def progress(sessions):
    verified = [s for s in sessions if s.get('eligible') and s.get('body') == 'real'
                and s.get('profile') == 'wearing' and s.get('complete') and not s.get('tripped')
                and s['metrics']['movement_s'] >= 30]
    # Defensive deduplication: copies of the same recording never earn extra progress.
    verified = list({s['id']: s for s in verified}.values())
    verified.sort(key=lambda s: s['started_at'])
    days = {datetime.fromtimestamp(s['started_at'], ZoneInfo('Asia/Taipei')).date() for s in verified}
    seconds = sum(s['metrics']['movement_s'] for s in verified)
    symmetric = [s for s in verified if s['metrics']['movement_s'] >= 60
                 and (s['metrics'].get('rom_symmetry') or 0) >= .9]
    definitions = [
        ('first', '第一步', '完成并收录一次活动至少 30 秒的穿戴记录', len(verified), 1, '↗'),
        ('days', '三日同行', '在 3 个不同日期留下穿戴运动记录', len(days), 3, '☀'),
        ('hour', '一小时积累', '累计记录 60 分钟穿戴活动', round(seconds / 60, 1), 60, '◷'),
        ('symmetry', '左右同行', '3 次活动至少 1 分钟的记录，左右运动幅度比达到 90%', len(symmetric), 3, '⇄'),
    ]
    return {'sessions': len(verified), 'days': len(days), 'movement_minutes': round(seconds / 60, 1),
            'badges': [{'id': key, 'title': title, 'description': desc, 'value': value,
                        'target': target, 'unlocked': value >= target, 'icon': icon}
                       for key, title, desc, value, target, icon in definitions]}
