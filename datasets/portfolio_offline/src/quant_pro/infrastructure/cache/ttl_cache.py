
from __future__ import annotations

import functools
import logging
import pickle
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class TTLCache:

    def __init__(self, ttl: float = 300.0, max_size: int = 1000) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str | bytes, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0


    def get(self, key: str | bytes) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str | bytes, value: Any) -> None:
        with self._lock:
            if key in self._store:
                self._store[key] = (value, time.monotonic())
                return
            while len(self._store) >= self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            self._store[key] = (value, time.monotonic())

    def invalidate(self, key: str | bytes) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
            }


    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: str | bytes) -> bool:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _, ts = entry
            return time.monotonic() - ts <= self._ttl




def _make_key(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    try:
        raw = pickle.dumps((func.__qualname__, args, sorted(kwargs.items())))
    except Exception:
        raw = repr((func.__qualname__, args, sorted(kwargs.items()))).encode()
    return raw


def cached(ttl: float = 300.0, max_size: int = 1000) -> Callable[[F], F]:

    def decorator(func: F) -> F:
        cache = TTLCache(ttl=ttl, max_size=max_size)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(func, args, kwargs)
            result = cache.get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        wrapper.__cache__ = cache
        return wrapper

    return decorator
