
from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class RedisClient:

    _client: Any

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: str = "1",
        password: str = "",
        decode_responses: bool = True,
        **kwargs: Any,
    ) -> None:
        import redis

        pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=decode_responses,
            socket_timeout=kwargs.pop("socket_timeout", 30),
            socket_connect_timeout=kwargs.pop("socket_connect_timeout", 10),
            **kwargs,
        )
        self._client = redis.Redis(connection_pool=pool)


    def _disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Disconnected from Redis database")

    def get_connect(self) -> Any:
        return self._client

    def __del__(self) -> None:
        if getattr(self, "_client", None):
            self._disconnect()


    def fetch_dict(self, hash_key: str, fields: Any = None) -> dict[str, Any]:
        if isinstance(fields, (str, int)):
            fields = [fields]
        if fields is not None:
            res: dict[str, Any] = {
                field: json.loads(value)
                for field, value in zip(
                    fields,
                    [
                        self._client.hget(hash_key, field)
                        for field in fields
                        if self._client.hget(hash_key, field) is not None
                    ],
                    strict=False,
                )
            }
        else:
            res = {
                field: json.loads(value) for field, value in self._client.hgetall(hash_key).items()
            }
        return res

    def fetch_dataframe(self, hash_key: str, fields: Any = None) -> pd.DataFrame | None:
        if isinstance(fields, (str, int)):
            fields = [fields]
        if fields is not None:
            raw = [
                json.loads(i)
                for i in [self._client.hget(hash_key, field) for field in fields]
                if i is not None
            ]
        else:
            raw = [json.loads(i) for i in self._client.hgetall(hash_key).values()]
        if raw:
            return self._parse_datetime_columns(pd.DataFrame(raw))
        return None

    def fetch_list_dataframes(self, hash_key: str, count: int = 1) -> list[pd.DataFrame]:
        return [
            self._parse_datetime_columns(pd.DataFrame(json.loads(i)))
            for i in self._client.lrange(hash_key, 0, count - 1)
        ]


    @staticmethod
    def _parse_datetime_columns(df: pd.DataFrame) -> pd.DataFrame:
        dt_cols = df.filter(regex=r"(?i)(date|time)").columns
        for c in dt_cols:
            col = df[c]
            if pd.api.types.is_numeric_dtype(col):
                non_na = col.dropna()
                if not non_na.empty:
                    vmax = non_na.max()
                    unit = "ms" if vmax > 1e11 else "s"
                    df[c] = pd.to_datetime(col, unit=unit, errors="coerce", utc=True)
            else:
                df[c] = pd.to_datetime(col, errors="coerce", utc=True)
        return df
