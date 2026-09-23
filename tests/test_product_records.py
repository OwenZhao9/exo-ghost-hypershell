import csv
import json
import math
import os
import time

import pytest

from product_features.records.metrics import REQUIRED, summarise
from product_features.records.importer import import_record, source_path


def row(t, **extra):
    return dict(host_t=t, ldeg=-10, rdeg=10, ldps=180, rdps=-90, cmd_l=1, cmd_r=-2, **extra)


def test_work_uses_radians_and_does_not_integrate_outages():
    _, metrics = summarise([row(100), row(100.1), row(200), row(200.1)])
    assert metrics['duration_s'] == .2
    assert metrics['gaps'] == 1
    assert metrics['left_command_work_j'] == pytest.approx(math.pi * .2, abs=.001)
    assert metrics['right_command_work_j'] == pytest.approx(math.pi * .2, abs=.001)
    assert metrics['rom_symmetry'] is None
    assert metrics['effort_saving_ratio'] is None


def test_bad_frame_breaks_integration():
    rows = [row(100), {**row(100.05), 'cmd_l': 'NaN'}, row(100.1), row(100.2)]
    _, m = summarise(rows)
    assert m['invalid_frames'] == 1 and m['duration_s'] == .1


def test_source_and_context_cannot_award_sim_or_table_records(tmp_path):
    path = tmp_path / 'session.csv'
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED); writer.writeheader()
        writer.writerows([row(100), row(100.1)])
    os.utime(path, (time.time() - 10, time.time() - 10))
    for body, profile, eligible in [('sim', 'wearing', False), ('real', 'table', False), ('real', 'wearing', True)]:
        path.with_suffix('.jsonl').write_text('\n'.join(json.dumps(r) for r in [
            {'kind': 'session', 'phase': 'start', 'body': body, 'profile': profile},
            {'kind': 'session', 'phase': 'end'}]))
        result = import_record(tmp_path, path.name, {'body': 'real', 'profile': 'wearing'})
        assert result['eligible'] is eligible


def test_traversal_and_external_symlink_are_rejected(tmp_path):
    root = tmp_path / 'records'; root.mkdir()
    outside = tmp_path / 'other.csv'; outside.write_text('secret')
    (root / 'alias.csv').symlink_to(outside)
    for name in ['../other.csv', 'alias.csv']:
        with pytest.raises(ValueError): source_path(root, name)
