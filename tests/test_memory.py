"""经验层：继承、回忆、沉淀。

两条不能破的规矩：
  1. 公开方法全部非阻塞——控制环调用它不能卡；
  2. 经验层自己出任何问题都不许影响控制。
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent.capsules import seed_capsules
from agent.memory import EVENT_QUERIES, GhostMemory


@pytest.fixture
def mem(tmp_path: Path):
    m = GhostMemory(db_path=str(tmp_path / "g.db")).start()
    m.wait_boot(5.0)
    yield m
    m.close()


# ---------------------------------------------------------------- 播种

def test_boot_seeds_the_capsules(mem):
    assert mem.inherited == len(seed_capsules())
    assert mem.seeded == len(seed_capsules())
    assert mem.errors == 0


def test_seeding_is_idempotent(tmp_path: Path):
    """同一个库起两次，条数不该翻倍——Capsule 的 id 是固定的。"""
    db = str(tmp_path / "g.db")
    first = GhostMemory(db_path=db).start(); first.wait_boot(5.0); first.close()
    second = GhostMemory(db_path=db).start(); second.wait_boot(5.0)
    assert second.inherited == first.inherited
    assert second.seeded == 0                      # 第二次没有新增
    second.close()


# ---------------------------------------------------------------- 回忆

def test_event_recall_finds_the_matching_capsule(mem):
    got: list = []
    mem.on_recall = got.append
    assert mem.recall_for_event("legs_offline") is True
    for _ in range(100):
        if got:
            break
        time.sleep(0.05)
    assert got, "回忆没有在 5 秒内返回"
    assert got[0].hits[0].asset.id == "exo-legs-offline-recover"


def test_unknown_event_is_not_queried(mem):
    assert mem.recall_for_event("什么鬼事件") is False


def test_every_event_query_hits_something(mem, tmp_path: Path):
    """EVENT_QUERIES 里每条查询词都必须真能查到东西，否则等于白写。

    注意这里自己开了一个 Store：GhostMemory 的那个绑在它的后台线程上，
    在测试线程里碰它 sqlite 会直接报错——这正是我们想要的行为。
    """
    from evomap_genes import Store
    probe = Store(backend="sqlite", db_path=str(tmp_path / "g.db"))
    for event, query in EVENT_QUERIES.items():
        assert probe.search(query, k=1), f"事件 {event} 的查询词「{query}」查不到任何经验"


def test_touching_the_store_from_another_thread_fails_loudly(mem):
    """把线程边界钉住：越界使用应该立刻报错，而不是悄悄损坏数据。"""
    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError):
        mem._store.search("腿板掉线", k=1)


# ---------------------------------------------------------------- 不阻塞、不炸

def test_public_methods_never_block_the_caller(mem):
    """控制环里可能会调到这些方法，必须立刻返回。"""
    t0 = time.perf_counter()
    for _ in range(200):
        mem.recall("腿板掉线")
        mem.note("压力测试", "partial")
    assert time.perf_counter() - t0 < 0.25, "公开方法阻塞了调用方"


def test_queue_overflow_drops_instead_of_blocking(tmp_path: Path):
    """队列满了要丢任务并计数，不能把调用方堵住。"""
    m = GhostMemory(db_path=str(tmp_path / "g.db"))
    for _ in range(500):                            # 没 start()，没人消费
        m.note("灌满队列")
    assert m.dropped > 0
    assert m._q.qsize() <= 64


def test_worker_errors_are_counted_not_raised(mem):
    def boom() -> None:
        raise RuntimeError("故意炸一个")
    mem._submit(boom)
    for _ in range(100):
        if mem.errors:
            break
        time.sleep(0.02)
    assert mem.errors == 1                          # 记一笔，但没有传播出来


def test_store_lives_on_the_worker_thread(mem):
    """evomap-genes 的 sqlite 连接绑线程，主线程碰它会直接报错——所以不准碰。"""
    holder: list = []
    mem._submit(lambda: holder.append(threading.get_ident()))
    for _ in range(100):
        if holder:
            break
        time.sleep(0.02)
    assert holder[0] != threading.get_ident()
    assert holder[0] == mem._thread.ident


def test_snapshot_is_json_safe(mem):
    import json
    mem.recall_for_event("legs_offline")
    time.sleep(0.5)
    json.dumps(mem.snapshot())                      # 会写进 status.json，不能有非 JSON 类型


# ---------------------------------------------------------------- 相似度门槛

def test_weak_hits_are_filtered_out(tmp_path: Path):
    """只因为都提到了'力矩'就命中的噪声，宁可不说也不能当建议念出来。"""
    from evomap_genes import Store
    got: list = []
    m = GhostMemory(db_path=str(tmp_path / "g.db"), on_recall=got.append, min_score=0.99).start()
    m.wait_boot(5.0)
    m.recall("腿板掉线")
    for _ in range(100):
        if got:
            break
        time.sleep(0.02)
    m.close()
    assert got[0].hits == []            # 门槛拉到 0.99，什么都不该通过
    assert got[0].weak > 0              # 但要如实说明有几条被挡掉了


def test_default_threshold_keeps_the_real_match(mem):
    got: list = []
    mem.on_recall = got.append
    mem.recall("急停 倾角 跌倒 安全")
    for _ in range(100):
        if got:
            break
        time.sleep(0.02)
    assert got[0].hits, "急停恢复流程应该能被查到"
    assert got[0].hits[0].asset.id == "exo-estop-recovery"
