"""
Lightweight time and SMT-call tracing helpers.

Tracing is disabled unless SYMBOLICANA_TRACE_PATH is set. Events are written as
JSON lines so evaluation scripts can aggregate T_align, T_smt, and SMT_calls
without scraping human-readable logs.
"""

from __future__ import annotations

import atexit
import contextlib
import functools
import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, DefaultDict, Iterator, Optional, TypeVar


F = TypeVar("F", bound=Callable[..., Any])


class TraceRecorder:
    def __init__(self) -> None:
        self.path = os.environ.get("SYMBOLICANA_TRACE_PATH")
        self.run_id = os.environ.get("SYMBOLICANA_TRACE_RUN_ID", "")
        self._lock = threading.Lock()
        self._counters: DefaultDict[str, int] = defaultdict(int)
        self._totals: DefaultDict[str, float] = defaultdict(float)
        if self.path:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            atexit.register(self.flush_summary)

    @property
    def enabled(self) -> bool:
        return bool(self.path)

    def event(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        record = {
            "ts": time.time(),
            "run_id": self.run_id,
            "event": event,
            **fields,
        }
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def add_counter(self, name: str, value: int = 1) -> None:
        if self.enabled:
            self._counters[name] += value

    def add_total(self, name: str, value: float) -> None:
        if self.enabled:
            self._totals[name] += value

    def flush_summary(self) -> None:
        if not self.enabled:
            return
        self.event(
            "summary",
            counters=dict(self._counters),
            totals=dict(self._totals),
        )


RECORDER = TraceRecorder()


@contextlib.contextmanager
def time_block(kind: str, name: str, **fields: Any) -> Iterator[dict]:
    start_wall = time.time()
    start = time.perf_counter()
    payload: dict[str, Any] = {}
    RECORDER.event(f"{kind}_start", name=name, **fields)
    try:
        yield payload
    finally:
        elapsed = time.perf_counter() - start
        RECORDER.add_total(f"{kind}_seconds", elapsed)
        RECORDER.event(
            f"{kind}_end",
            name=name,
            elapsed=elapsed,
            start_ts=start_wall,
            end_ts=time.time(),
            **fields,
            **payload,
        )


def time_function(kind: str, name: Optional[str] = None, **fields: Any) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        label = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with time_block(kind, label, **fields):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def trace_smt_check(solver: Any, name: str, **fields: Any) -> Any:
    with time_block("smt", name, **fields) as payload:
        result = solver.check()
        payload["result"] = str(result)
    RECORDER.add_counter("SMT_calls", 1)
    return result
