
from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "ClickHouseClient": (
        "quant_pro.infrastructure.clickhouse.client",
        "ClickHouseClient",
    ),
    "DatabasePort": (
        "quant_pro.infrastructure.database.client",
        "DatabasePort",
    ),
    "RedisClient": (
        "quant_pro.infrastructure.redis.client",
        "RedisClient",
    ),
    "RedisDataFetcher": (
        "quant_pro.infrastructure.redis.fetcher",
        "RedisDataFetcher",
    ),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = module.__dict__[attr_name]
    globals()[name] = value
    return value


__all__ = [
    "DatabasePort",
    "ClickHouseClient",
    "RedisClient",
    "RedisDataFetcher",
]
