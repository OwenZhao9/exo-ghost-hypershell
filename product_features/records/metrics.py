"""Streaming measurements from recorded device samples, never a muscle-strength estimate."""
import math

REQUIRED = ('host_t', 'ldeg', 'rdeg', 'ldps', 'rdps', 'cmd_l', 'cmd_r')


def summarise(rows):
    count = invalid = gaps = 0
    first = last = previous = None
    elapsed = movement = left_work = right_work = 0.0
    low = [math.inf, math.inf]; high = [-math.inf, -math.inf]
    windows = {}
    for row in rows:
        try:
            values = [float(row[k]) for k in REQUIRED]
            if not all(math.isfinite(v) for v in values):
                raise ValueError()
            t, left, right, lv, rv, lt, rt = values
            if t <= 0 or max(abs(lv), abs(rv)) >= 3276.7 or max(abs(left), abs(right)) > 180:
                raise ValueError()
            if last is not None and t <= last:
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1; previous = None; continue
        if first is None:
            first = t
        last = t; count += 1
        low = [min(low[0], left), min(low[1], right)]
        high = [max(high[0], left), max(high[1], right)]
        if previous is not None:
            dt = t - previous[0]
            if 0 < dt <= .25:
                elapsed += dt
                if max(abs(lv), abs(rv)) > 5:
                    movement += dt
                left_work += (previous[5] * math.radians(previous[3]) + lt * math.radians(lv)) * dt / 2
                right_work += (previous[6] * math.radians(previous[4]) + rt * math.radians(rv)) * dt / 2
            else:
                gaps += 1
        bucket = int((t - first) // 60)
        w = windows.setdefault(bucket, [0.0, 0.0, 0])
        w[0] += abs(lv); w[1] += abs(rv); w[2] += 1
        previous = values
    if count < 2 or elapsed <= 0:
        raise ValueError('有效连续数据不足，无法生成运动记录')
    lrom, rrom = high[0] - low[0], high[1] - low[1]
    symmetry = min(lrom, rrom) / max(lrom, rrom) if min(lrom, rrom) >= 5 else None
    metrics = {
        'frames': count, 'invalid_frames': invalid, 'gaps': gaps,
        'duration_s': round(elapsed, 3), 'span_s': round(last - first, 3),
        'movement_s': round(movement, 3),
        'left_rom_deg': round(lrom, 2), 'right_rom_deg': round(rrom, 2),
        'rom_symmetry': round(symmetry, 4) if symmetry is not None else None,
        'left_command_work_j': round(left_work, 3), 'right_command_work_j': round(right_work, 3),
        'muscle_strength': None, 'effort_saving_ratio': None, 'fatigue': None,
        'speed_windows': [{'minute': k, 'left_dps': round(v[0] / v[2], 2),
                           'right_dps': round(v[1] / v[2], 2)} for k, v in sorted(windows.items())],
    }
    return first, metrics
