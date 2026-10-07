
from __future__ import annotations

from typing import Any, cast

from quant_pro.infrastructure.cache import TTLCache
from quant_pro.infrastructure.clickhouse import queries as Q


class SuspendDataFetcher:

    def __init__(self, client: Any) -> None:
        self.client = client
        self._cache = TTLCache(ttl=3_600.0, max_size=200)

    def get_suspend_stocks(self, date: str) -> list[str]:
        cache_key = f"suspend:{date}"
        cached_result = self._cache.get(cache_key)
        if cached_result is not None:
            return cast(list[str], cached_result)
        sql = Q.SUSPEND_STOCKS_QUERY.format(date=date)
        result = self.client.query(sql)
        stocks = list(result["instrument"].tolist())
        self._cache.set(cache_key, stocks)
        return [str(s) for s in stocks]
