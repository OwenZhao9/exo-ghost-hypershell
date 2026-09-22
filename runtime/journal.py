"""会话流水：把这一次跑了什么、出了什么事、Ghost 怎么判的，逐条落盘。

为什么要有它：终端会滚走，网页刷新就没了，CSV 里只有传感器数字。
评委问"你凭什么说它自己处理了故障"，得能把那一刻的记录翻出来——
带时间戳、带当时的证据、带处置结果。交付单（`report/`）就是读这个文件生成的。

格式是 JSONL：一行一条，追加写，进程被 Ctrl-C 掉也不会丢已经写进去的部分。
每条至少有 `t`（time.time）和 `kind`。写失败一律吞掉——记录不成功不该影响控制。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

__all__ = ["KINDS", "Journal", "read_journal"]

#: 记录种类 -> 一句话说明。交付单按这个分组。
KINDS = {
    "session": "会话开始／结束",
    "event": "设备事件（掉线、重连、急停……）",
    "command": "有人或 Ghost 下发的命令",
    "decision": "直觉层的一次判断",
    "recall": "经验层的一次回忆",
    "note": "其他说明",
}


class Journal:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path: Optional[str] = None
        self.n = 0
        self._lock = threading.Lock()
        if path:
            self.set_path(path)

    def set_path(self, path: str) -> None:
        """落盘路径要等桥接层开好 CSV 才知道，所以允许事后设。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path

    def write(self, kind: str, **fields: Any) -> None:
        if not self.path:
            return
        rec = {"t": time.time(), "kind": kind, **fields}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        try:
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self.n += 1
        except Exception:
            pass          # 流水写不进去不该影响控制


def read_journal(path: str) -> list[dict]:
    """读回一整份流水。坏行跳过——半截 JSON 不该让交付单生成失败。"""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out
