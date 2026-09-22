"""会话落盘：把每一帧写成 CSV。

每次 ENABLE 开一个新文件，文件名带时间戳。列顺序与 `Sample` 的字段顺序一致，
下游（回放、辨识、回归测试）都按列名读，不按位置。
"""
from __future__ import annotations

import csv
import os
import time
from dataclasses import asdict, fields
from typing import Optional

from .protocol import Sample


class SessionLogger:
    """一次会话一个 CSV 文件。未指定目录时什么也不做（空对象）。"""

    def __init__(self, log_dir: Optional[str] = "data", prefix: str = "session"):
        self.log_dir = log_dir
        self.prefix = prefix
        self.path: Optional[str] = None
        self._f = None
        self._w = None

    def open(self) -> Optional[str]:
        if not self.log_dir or self._w is not None:
            return self.path
        os.makedirs(self.log_dir, exist_ok=True)
        self.path = os.path.join(self.log_dir, time.strftime(f"{self.prefix}_%Y%m%d_%H%M%S.csv"))
        self._f = open(self.path, "w", newline="", buffering=1 << 16)
        self._w = csv.writer(self._f)
        self._w.writerow([f.name for f in fields(Sample)])
        return self.path

    def write(self, s: Sample) -> None:
        if self._w is not None:
            self._w.writerow(asdict(s).values())

    def close(self) -> None:
        try:
            if self._f:
                self._f.flush()
                self._f.close()
        finally:
            self._f = None
            self._w = None
