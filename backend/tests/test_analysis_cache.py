"""Single-flight cache: a burst of identical requests computes once (no stampede)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.session import build_engine
from app.services.analysis import AnalysisCache


def test_concurrent_requests_for_one_key_compute_once():
    cache = AnalysisCache()
    calls = 0
    lock = threading.Lock()

    def compute():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.05)
        return "result"

    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(lambda _: cache.get_or_compute(("k",), compute), range(48)))
    assert results == ["result"] * 48
    assert calls == 1


def test_a_failed_computation_is_not_cached_and_can_be_retried():
    cache = AnalysisCache()

    def boom():
        raise RuntimeError("solver down")

    with pytest.raises(RuntimeError):
        cache.get_or_compute(("k",), boom)
    assert cache.get_or_compute(("k",), lambda: "ok") == "ok"


def test_file_sqlite_pool_covers_the_worker_threadpool(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'pool.db'}")
    assert engine.pool.size() + engine.pool._max_overflow >= 40  # noqa: SLF001
