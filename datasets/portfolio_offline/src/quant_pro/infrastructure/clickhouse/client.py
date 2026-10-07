
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ClickHouseClient:

    _client: Any

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9000,
        database: str = "default",
        user: str = "default",
        password: str = "",
        **kwargs: Any,
    ) -> None:
        from clickhouse_driver import Client

        self._client = Client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            **kwargs,
        )


    def query(self, sql: str) -> pd.DataFrame:
        logger.debug("Executing query: %s...", sql[:100])
        result: pd.DataFrame = self._client.query_dataframe(sql)
        logger.debug("Query returned %d rows", len(result))
        return result

    def _disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None
            logger.info("Disconnected from ClickHouse database")

    def get_connect(self) -> Any:
        return self._client


    def insert(self, query: str, df: pd.DataFrame) -> None:
        if df.empty:
            logger.warning("DataFrame is empty, skipping insert")
            return

        logger.debug("Inserting %d rows using query: %s...", len(df), query[:100])
        self._client.insert_dataframe(query, df, settings={"use_numpy": True})
        logger.info("Successfully inserted %d rows into the database", len(df))

    def __del__(self) -> None:
        if getattr(self, "_client", None):
            self._disconnect()
