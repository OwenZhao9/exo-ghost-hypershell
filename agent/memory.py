"""Ghost 的经验资产：启动时继承，遇事时回忆，结束时沉淀。

用 [evomap-genes](https://github.com/OwenZhao9/evomap-genes) 存取 EvoMap GEP 格式的
Gene / Capsule / EvolutionEvent。默认纯本地 sqlite，断网照常工作；
默认不访问远端；显式打开公开检索后，只发送固定的通用事件关键词，
不上传传感器数据，不注册节点，也不下载或自动执行外部策略。

**硬规矩：查库和网络请求会阻塞，绝不能在串口读线程里发生。**
所以这里所有公开方法都只往有界队列里放任务，由各自后台线程去做；
队列满了就丢任务并计数，宁可少记一条经验，也不许拖慢 180 Hz 的控制环。

evomap-genes 明说实例不是线程安全的、sqlite 连接保持 `check_same_thread=True`，
所以 `Store` 是在**后台线程里**构造的（`_worker` 的第一件事），主线程一次都不碰它。
主线程只读 GhostMemory 自己的普通属性（inherited / last / …），那些是纯数据。
现有 node_secret 参数保留旧版 Store 用法；控制服务不会传它，公开检索也不使用它。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Optional

from evomap_genes import Capsule, Event, SearchHit, Store

from .capsules import seed_capsules
from .evomap_public import EVENT_SEARCHES, search_event

__all__ = ["GhostMemory", "Recall"]

#: 设备事件 -> 拿去查经验的关键词。事件名见 runtime/events.py。
EVENT_QUERIES = {
    "legs_offline": "腿板掉线 关节角度全零 恢复",
    "legs_online": "腿板上线 静默期 自检快动",
    "reconnected": "串口重连 掉线 usb",
    "stall": "串口 数据流中断 掉线 usb",
    "stream_slow": "数据流变慢 设备重启 掉线",
    "trip": "急停 倾角 跌倒 安全",
    "stalled": "堵转 限位 力矩 过流",
    "port_lost": "串口找不到 设备消失 usb 掉线",
}

_QUEUE_MAX = 64          # 满了就丢：经验可以少记一条，控制环不能卡一帧

#: 低于这个相似度的命中一律不展示。实测真正对得上的命中在 0.7~0.9，
#: 0.2 上下的是"只因为都提到了'力矩'"这种噪声——把噪声当建议念出来比不说更糟。
MIN_SCORE = 0.40


class Recall:
    """一次回忆的结果，给界面用。"""

    __slots__ = ("query", "t", "hits", "weak")

    def __init__(self, query: str, hits: list[SearchHit]) -> None:
        self.query = query
        self.t = time.time()
        self.hits = hits
        self.weak = 0                  # 查到了但相似度不够、没拿出来的条数

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "t": self.t,
            "weak": self.weak,
            "hits": [
                {
                    "id": h.asset.id,
                    "title": h.asset.title,
                    "score": round(h.score, 3),
                    "why": h.why,
                    "source": h.source,
                    "steps": list(getattr(h.asset, "strategy_steps", ()))[:6],
                }
                for h in self.hits
            ],
        }


class GhostMemory:
    def __init__(self, db_path: str = "data/genes.db", author: str = "exo-ghost",
                 timeout_s: float = 3.0, node_secret: Optional[str] = None,
                 on_recall: Optional[Callable[[Recall], None]] = None,
                 min_score: float = MIN_SCORE, evomap_read: bool = False,
                 on_evomap: Optional[Callable[[dict], None]] = None) -> None:
        # Store 不在这里构造：它要绑在后台线程上（见模块 docstring）
        self._store_args = dict(backend="evomap" if node_secret else "sqlite",
                                db_path=db_path, timeout_s=timeout_s, author=author,
                                api_key=node_secret)
        # 带下划线是认真的：这个连接绑在后台线程上，别的线程碰它 sqlite 会直接报错。
        # 要在别的线程查同一个库，请自己开一个 Store 实例（evomap-genes 的 README 也这么说）。
        self._store: Optional[Store] = None
        self.author = author
        self.on_recall = on_recall
        self.on_evomap = on_evomap
        self.evomap_read = evomap_read
        self.min_score = min_score
        self.inherited = 0                    # 启动时库里已有多少条经验
        self.seeded = 0                       # 本次播种写进去几条
        self.last: Optional[Recall] = None
        self.dropped = 0                      # 因为队列满而丢掉的任务数
        self.errors = 0
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()         # Store 建好了没
        self._booted = threading.Event()        # 播种 + 报数做完了没
        self._remote_q: queue.Queue = queue.Queue(maxsize=8)
        self._remote_thread: Optional[threading.Thread] = None
        self._remote_stop = threading.Event()
        self._remote_requested: dict[str, float] = {}
        self._remote_state: dict[str, Any] = {
            "enabled": evomap_read, "state": "idle", "event": None,
            "references": [], "error": None, "t": None,
        }

    # ---------------- 生命周期 ----------------
    def start(self) -> "GhostMemory":
        if self.evomap_read:
            self._remote_thread = threading.Thread(target=self._remote_worker,
                                                   name="ghost-evomap-read", daemon=True)
            self._remote_thread.start()
        self._thread = threading.Thread(target=self._worker, name="ghost-memory", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)           # 只等建连接，不等查库
        self._submit(self._boot)
        return self

    def wait_boot(self, timeout: float = 3.0) -> bool:
        """等播种完成。**只在启动时调用**（要打印"继承了 N 条经验"），控制环里不准用。"""
        return self._booted.wait(timeout)

    def close(self, drain_s: float = 2.0) -> None:
        """把队列里剩下的做完（最多等 drain_s），然后停线程。"""
        deadline = time.time() + drain_s
        while not self._q.empty() and time.time() < deadline:
            time.sleep(0.02)
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=1.0)
        self._remote_stop.set()
        try:
            self._remote_q.put_nowait(None)
        except queue.Full:
            pass
        if self._remote_thread:
            self._remote_thread.join(timeout=2.0)

    # ---------------- 公开接口：全部非阻塞 ----------------
    def recall(self, query: str, k: int = 3) -> None:
        """按关键词回忆。结果通过 on_recall 回调送出，同时留在 self.last。"""
        self._submit(lambda: self._do_recall(query, k))

    def recall_for_event(self, event: str, k: int = 2) -> bool:
        """设备事件触发的回忆。返回是否有对应的查询词（没有就不查，免得刷屏）。"""
        kind = event.split(":", 1)[0]
        q = EVENT_QUERIES.get(kind)
        if not q:
            return False
        self.recall(q, k)
        if self.evomap_read and kind in EVENT_SEARCHES:
            now = time.monotonic()
            if now - self._remote_requested.get(kind, -1e9) >= 30.0:
                try:
                    self._remote_q.put_nowait(kind)
                    self._remote_requested[kind] = now
                except queue.Full:
                    self.dropped += 1
        return True

    def note(self, intent: str, outcome: str = "partial", *,
             subject_id: Optional[str] = None, payload: Optional[dict] = None,
             mutations: Optional[list[dict]] = None) -> None:
        """记一条 EvolutionEvent：想做什么、试了什么、结果如何。"""
        ev = Event(id=f"{self.author}-{time.time():.6f}", t=time.time(), actor=self.author,
                   intent=intent, mutations=mutations or [], outcome=outcome,
                   subject_id=subject_id, payload=payload)
        self._submit(lambda: self._store.record(ev))

    def learn(self, capsule: Capsule) -> None:
        """沉淀一条新的验证过的修复。"""
        self._submit(lambda: self._store.store(capsule))

    def snapshot(self) -> dict[str, Any]:
        """给仪表盘的一小块状态，非阻塞、随时可读。"""
        return {
            "inherited": self.inherited,
            "seeded": self.seeded,
            "pending": self._q.qsize(),
            "dropped": self.dropped,
            "errors": self.errors,
            "last": None if self.last is None else self.last.to_dict(),
            "evomap": self._remote_state,
        }

    def _remote_worker(self) -> None:
        """Network IO is separate from both the serial reader and local sqlite worker."""
        while not self._remote_stop.is_set():
            event = self._remote_q.get()
            if event is None:
                break
            self._remote_state = {
                "enabled": True, "state": "searching", "event": event,
                "references": [], "error": None, "t": time.time(),
            }
            try:
                references = search_event(event)
                result = {
                    "enabled": True, "state": "ready", "event": event,
                    "references": references, "error": None, "t": time.time(),
                }
            except Exception as exc:
                result = {
                    "enabled": True, "state": "error", "event": event,
                    "references": [], "error": type(exc).__name__, "t": time.time(),
                }
            self._remote_state = result
            if self.on_evomap:
                try:
                    self.on_evomap(result)
                except Exception:
                    self.errors += 1

    # ---------------- 后台线程 ----------------
    def _submit(self, fn: Callable[[], None]) -> None:
        try:
            self._q.put_nowait(fn)
        except queue.Full:
            self.dropped += 1

    def _worker(self) -> None:
        try:
            self._store = Store(**self._store_args)   # sqlite 连接绑在这个线程上
        except Exception:
            self.errors += 1
            self._ready.set()
            return
        self._ready.set()
        while not self._stop.is_set():
            task = self._q.get()
            if task is None:
                break
            try:
                task()
            except Exception:                 # 经验层出问题绝不能影响控制
                self.errors += 1
            finally:
                if task is self._boot:        # 播种失败也要放行，不能让启动卡住
                    self._booted.set()

    def _boot(self) -> None:
        """播种 + 报数。store() 用固定 id，重复播种是幂等的。"""
        before = int(self._store.stats().get("assets", 0))
        for c in seed_capsules():
            self._store.store(c)
        after = int(self._store.stats().get("assets", 0))
        self.inherited = after
        self.seeded = max(0, after - before)
        self.note("启动：继承经验库", "success", payload={"assets": after})
        self._booted.set()

    def _do_recall(self, query: str, k: int) -> None:
        raw = self._store.search(query, k=k)
        hits = [h for h in raw if h.score >= self.min_score]
        self.last = Recall(query, hits)
        self.last.weak = len(raw) - len(hits)     # 被相似度门槛挡掉几条
        if self.on_recall:
            self.on_recall(self.last)
