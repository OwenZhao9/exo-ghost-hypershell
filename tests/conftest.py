"""测试公用夹具。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "data" / "samples"
BASELINES = Path(__file__).parent / "baselines"


def load_samples(path: Path):
    """把录制的 CSV 读成 Sample 列表，顺序与录制时一致。"""
    from bridge.serial_io import Sample

    out = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            out.append(Sample(**{k: float(v) for k, v in row.items()}))
    return out


@pytest.fixture(scope="session")
def sample_files() -> list[Path]:
    files = sorted(SAMPLES.glob("*.csv"))
    assert files, f"没有样本数据：{SAMPLES}"
    return files
