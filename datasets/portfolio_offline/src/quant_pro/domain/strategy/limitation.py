
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


class Limitation:

    def __init__(self) -> None:
        self.datas = self._load_data()

    def _load_data(self) -> object:
        from data_process import align_datas, datas, load_factors

        load_factors(
            [
                "close",
                "open_up_limit",
                "open_down_limit",
                "up_one_line",
                "down_one_line",
            ]
        )
        return align_datas("close", dataset=datas.day, inplace=False)

    def _get_limit_data(self, dt: datetime, column_name: str) -> pd.Series:
        try:
            data_slice = self.datas[column_name].loc[dt:]
            if len(data_slice) == 0:
                logger.warning("No data found for %s starting from %s", column_name, dt)
                return pd.Series(dtype=bool)
            with pd.option_context("future.no_silent_downcasting", True):
                result = data_slice.head(2).iloc[-1].fillna(False).infer_objects(copy=False)
            return result
        except (KeyError, IndexError) as e:
            logger.error("Error getting %s data for %s: %s", column_name, dt, e)
            return pd.Series(dtype=bool)

    def get_buy_limit(self, dt: datetime) -> pd.Series:
        return self._get_limit_data(dt, "open_up_limit")

    def get_sell_limit(self, dt: datetime) -> pd.Series:
        return self._get_limit_data(dt, "down_one_line")

    def get_short_sell_limit(self, dt: datetime) -> pd.Series:
        return self._get_limit_data(dt, "open_down_limit")

    def get_short_buy_limit(self, dt: datetime) -> pd.Series:
        return self._get_limit_data(dt, "up_one_line")


__all__ = ["Limitation"]
