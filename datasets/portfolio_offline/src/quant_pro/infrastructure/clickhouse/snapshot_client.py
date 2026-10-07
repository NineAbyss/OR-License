
from __future__ import annotations

from typing import Any

from quant_pro.infrastructure.clickhouse.canonical_range_store import (
    query_canonical_range,
)
from quant_pro.infrastructure.snapshot_store import SnapshotStore


class SnapshotClickHouseClient:
    def __init__(self, delegate: Any | None = None) -> None:
        self._delegate = delegate
        self._store = SnapshotStore("clickhouse_queries")

    def query(self, sql: str) -> Any:
        canonical = query_canonical_range(sql)
        if canonical is not None:
            return canonical
        return self._store.call(
            "query", (sql,), {}, lambda: self._require_delegate().query(sql)
        )

    def get_connect(self) -> Any:
        return self

    def insert(self, query: str, df: Any) -> None:
        if self._delegate is None:
            raise RuntimeError("offline ClickHouse snapshot is read-only")
        self._delegate.insert(query, df)

    def _disconnect(self) -> None:
        if self._delegate is not None and hasattr(self._delegate, "_disconnect"):
            self._delegate._disconnect()

    def _require_delegate(self) -> Any:
        if self._delegate is None:
            raise RuntimeError("live ClickHouse delegate is unavailable in replay mode")
        return self._delegate
