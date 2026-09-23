from product_features.growth.rules import progress


def session(i, **fields):
    return {'id': str(i), 'started_at': 1790070000 + i * 86400, 'eligible': True,
            'body': 'real', 'profile': 'wearing', 'complete': True, 'tripped': None,
            'metrics': {'movement_s': 1200, 'rom_symmetry': .95}, **fields}


def test_real_completed_motion_unlocks_and_duplicates_do_not_count():
    data = progress([session(1), session(2), session(3), session(3)])
    assert data['sessions'] == 3 and data['days'] == 3
    assert all(b['unlocked'] for b in data['badges'])


def test_bench_sim_unknown_incomplete_tripped_and_stationary_cannot_earn():
    records = [session(1, body='sim'), session(2, profile='table'), session(3, eligible=False),
               session(4, complete=False), session(5, tripped='stop'),
               session(6, metrics={'movement_s': 0, 'rom_symmetry': 1})]
    assert progress(records)['sessions'] == 0
    assert not any(b['unlocked'] for b in progress(records)['badges'])
