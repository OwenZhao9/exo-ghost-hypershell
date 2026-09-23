import csv
import hashlib
import json
import re
import time
from pathlib import Path

from .metrics import summarise


def source_path(root: Path, filename: str):
    if not isinstance(filename, str) or not re.fullmatch(r'[\w. -]+\.csv', filename) or len(filename) > 200:
        raise ValueError('请选择记录列表中的 CSV 文件')
    path = (root / filename).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('记录不存在或不在指定目录内')
    return path


def journal_metadata(path):
    start = end = None
    journal = path.with_suffix('.jsonl')
    if journal.is_symlink() or not journal.is_file():
        return {}, {}
    with journal.open(encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or record.get('kind') != 'session':
                    continue
                if record.get('phase') == 'start': start = record
                if record.get('phase') == 'end': end = record
            except (ValueError, UnicodeError):
                continue
    return start or {}, end or {}


def import_record(root, filename, context):
    path = source_path(root, filename)
    before = path.stat()
    if before.st_size > 512 * 1024 * 1024:
        raise ValueError('记录超过 512 MB，请先按会话拆分')
    if time.time() - before.st_mtime < 2:
        raise ValueError('记录仍在写入，请结束本次记录后再收录')
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    with path.open(newline='', encoding='utf-8-sig') as f:
        started, metrics = summarise(csv.DictReader(f))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('记录仍在变化，请稍后重试')
    start, end = journal_metadata(path)
    body, profile = start.get('body', 'unknown'), start.get('profile', 'unknown')
    if body not in {'real', 'sim'}: body = 'unknown'
    if profile not in {'wearing', 'table'}: profile = 'unknown'
    label = str(context.get('label', '')).strip()[:100] or filename
    route = str(context.get('route', '')).strip()[:100]
    return {
        'schema_version': 1, 'id': digest, 'started_at': started,
        'source_file': filename, 'body': body, 'profile': profile,
        'complete': bool(end), 'eligible': body == 'real' and profile == 'wearing' and bool(end),
        'tripped': end.get('tripped'), 'context': {'label': label, 'route': route},
        'metrics': metrics,
    }
