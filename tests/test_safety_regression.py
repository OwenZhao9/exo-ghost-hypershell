"""安全层回归测试（特征测试 / characterization test）。

把 `control.safety.SafetyMonitor` 当前的行为逐帧录成基准，之后无论怎么重构
（拆文件、换成 fly-reflex 后端），**同一批输入必须产出逐字节相同的结果**。

基准文件在 tests/baselines/*.json，由本文件在缺失时自动生成；
一旦生成就当成事实标准，**不准为了让测试通过而重新生成**——
行为真要变，必须是人明确决定，并在 commit 里说清为什么。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from control.safety import PROFILES, SafetyMonitor
from tests.conftest import BASELINES, load_samples

# 逐帧判定时用录制的 host_t 作为时间源，保证可复现（库内不准用 time.time）
PROFILE_NAMES = ["table", "wearing"]


def _run(profile_name: str, samples) -> dict:
    """跑一遍安全层，把所有可观察输出录下来。"""
    mon = SafetyMonitor(PROFILES[profile_name])
    trips: list[dict] = []
    scales: list[float] = []
    for i, s in enumerate(samples):
        why = mon.trip(s)
        if why and not trips:                      # 只记第一次触发（之后调用方会急停）
            trips.append({"frame": i, "t_rel": round(s.host_t - samples[0].host_t, 4), "reason": why})
        sc = mon.assist_scale(s, 0.3, 0.3)         # 用固定的名义力矩，隔离出渐弱逻辑本身
        scales.append(round(sc, 6))
    return {
        "n_frames": len(samples),
        "first_trip": trips[0] if trips else None,
        "neutral_l": None if mon.neutral_l is None else round(mon.neutral_l, 4),
        "neutral_r": None if mon.neutral_r is None else round(mon.neutral_r, 4),
        "scale_min": min(scales),
        "scale_mean": round(sum(scales) / len(scales), 6),
        "scale_frames_below_1": sum(1 for x in scales if x < 1.0),
        "scale_frames_zero": sum(1 for x in scales if x == 0.0),
        "scale_head": scales[:20],
        "scale_tail": scales[-20:],
    }


def _baseline_path(profile_name: str, csv_path: Path) -> Path:
    return BASELINES / f"{csv_path.stem}__{profile_name}.json"


@pytest.mark.parametrize("profile_name", PROFILE_NAMES)
def test_safety_behaviour_matches_baseline(profile_name, sample_files):
    generated: list[str] = []
    for csv_path in sample_files:
        samples = load_samples(csv_path)
        got = _run(profile_name, samples)
        ref_path = _baseline_path(profile_name, csv_path)
        if not ref_path.exists():                  # 缺基准就补录，一次补全再 skip
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_text(json.dumps(got, ensure_ascii=False, indent=2), encoding="utf-8")
            generated.append(ref_path.name)
            continue
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        assert got == ref, (
            f"{csv_path.name} / {profile_name} 的安全层行为变了。\n"
            f"如果这是有意的改动，删掉 {ref_path.name} 重新生成并在 commit 里说明原因。"
        )
    if generated:
        pytest.skip(f"已生成基准 {', '.join(generated)}，提交后重跑即为回归测试")


def test_determinism(sample_files):
    """同一份输入跑两遍，结果必须完全一致（不准依赖 time.time 或随机数）。"""
    samples = load_samples(sample_files[0])
    assert _run("table", samples) == _run("table", samples)


def test_trip_is_latched_by_caller_contract():
    """SafetyMonitor.trip 本身不锁存，锁存由调用方负责——记录这个事实，改了要知道。"""
    from bridge.serial_io import Sample

    mon = SafetyMonitor(PROFILES["wearing"], warmup_s=0.0)
    base = dict(ms=0, pitch=0, roll=0, yaw=0, gx=0, gy=0, gz=0,
                ax=0, ay=0, az=1.0, kpa=100.0, ldeg=0, rdeg=0, ldps=0, rdps=0,
                cmd_l=0.0, cmd_r=0.0)
    mon.trip(Sample(host_t=0.0, **base))
    bad = Sample(host_t=1.0, **{**base, "ax": 5.0})
    assert mon.trip(bad) is not None
    good = Sample(host_t=1.1, **base)
    assert mon.trip(good) is None, "trip() 是无状态判定，不该自己锁存"


def test_saturated_joint_velocity_is_ignored():
    """编码器饱和值 ±3276.7 不该触发关节超速急停。"""
    from bridge.serial_io import Sample

    mon = SafetyMonitor(PROFILES["wearing"], warmup_s=0.0)
    base = dict(ms=0, pitch=0, roll=0, yaw=0, gx=0, gy=0, gz=0,
                ax=0, ay=0, az=1.0, kpa=100.0, ldeg=0, rdeg=0, rdps=0,
                cmd_l=0.0, cmd_r=0.0)
    mon.trip(Sample(host_t=0.0, ldps=0.0, **base))
    for i in range(5):
        assert mon.trip(Sample(host_t=1.0 + i * 0.006, ldps=3276.7, **base)) is None


def test_assist_scale_tapers_with_speed():
    """速度越高 assist 渐弱系数越小，且到硬阈值必须为 0。"""
    from bridge.serial_io import Sample

    p = PROFILES["table"]
    mon = SafetyMonitor(p, warmup_s=0.0)
    base = dict(ms=0, pitch=0, roll=0, yaw=0, gx=0, gy=0, gz=0,
                ax=0, ay=0, az=1.0, kpa=100.0, ldeg=0, rdeg=0, rdps=0,
                cmd_l=0.0, cmd_r=0.0)
    mon.trip(Sample(host_t=0.0, ldps=0.0, **base))          # 确立中立位
    slow = mon.assist_scale(Sample(host_t=1.0, ldps=p.assist_dps_soft * 0.5, **base), 0.0, 0.0)
    mid = mon.assist_scale(Sample(host_t=1.01, ldps=(p.assist_dps_soft + p.assist_dps_hard) / 2, **base), 0.0, 0.0)
    fast = mon.assist_scale(Sample(host_t=1.02, ldps=p.assist_dps_hard * 1.2, **base), 0.0, 0.0)
    assert math.isclose(slow, 1.0)
    assert 0.0 < mid < 1.0
    assert fast == 0.0
