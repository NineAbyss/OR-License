
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from quant_pro.domain.strategy.price_utils import batch_get_none_close, get_none_close

logger = logging.getLogger(__name__)


class SizeRecorder:

    def __init__(self) -> None:
        self.size_recorder: dict[str, int] = {}

    def get_size(self, stockcode: str) -> int:
        return self.size_recorder.get(stockcode, 0)

    def set_size(self, stockcode: str, size: int) -> None:
        self.size_recorder[stockcode] = size

    def ad_size(self, stockcode: str, size: int) -> None:
        if stockcode in self.size_recorder:
            self.size_recorder[stockcode] += size
        else:
            self.size_recorder[stockcode] = size

    def rm_size(self, stockcode: str, size: int = -1) -> None:
        current_size = self.size_recorder.get(stockcode, None)
        if current_size is None:
            return
        if size == -1:
            del self.size_recorder[stockcode]
        else:
            new_size = current_size - size
            if new_size <= 0:
                del self.size_recorder[stockcode]
            else:
                self.size_recorder[stockcode] = new_size

    def rm_size_future(self, stockcode: str, size: int = -1) -> None:
        if stockcode not in self.size_recorder:
            self.size_recorder[stockcode] = 0
        self.size_recorder[stockcode] -= size

    def add_size_future(self, stockcode: str, size: int) -> None:
        self.size_recorder[stockcode] += size

    def get_position(
        self, today: datetime, next_trade_day: datetime | None = None
    ) -> tuple[pd.DataFrame, list[str]]:
        if not self.size_recorder:
            return pd.DataFrame(columns=["stockcode", "volume", "close"]), []

        stocks = list(self.size_recorder.keys())
        volumes = list(self.size_recorder.values())

        try:
            today_closes = batch_get_none_close(today, stocks)
        except Exception as e:
            logger.error("批量获取价格数据时出错: %s。降级到逐个获取", e)
            today_closes = []
            for stock in stocks:
                try:
                    today_closes.append(get_none_close(today, stock))
                except Exception:
                    today_closes.append(None)

        res = pd.DataFrame({"stockcode": stocks, "volume": volumes, "close": today_closes})

        return res, []


class LongShortSizeRecorder:

    def __init__(self, ss_id_df: pd.DataFrame) -> None:
        self.size: dict[str, int] = {}
        self.money: dict[str, float] = {}
        self.apply_rate: dict[str, float] = {}
        self.hold_days: dict[str, int] = {}
        self.open_price: dict[str, float] = {}
        self.exec_size: dict[str, int] = {}
        self.partial_order: dict[int, object] = {}
        self.instrument_id_set: dict[str, set[str]] = {}
        self.ss_id_df = ss_id_df

    def add_short_item(
        self,
        stockcode: str,
        size: int,
        money: float,
        apply_rate: float,
        open_price: float,
    ) -> None:
        stockcode = str(stockcode)

        if stockcode in self.size:
            self.size[stockcode] += size
            self.money[stockcode] += money
            self.open_price[stockcode] = self.money[stockcode] / self.size[stockcode]
        else:
            self.size[stockcode] = size
            self.money[stockcode] = money
            self.apply_rate[stockcode] = apply_rate
            self.hold_days[stockcode] = 1
            self.open_price[stockcode] = open_price

        instrument = self._lookup_ss_id(stockcode)["instrument"]
        if instrument not in self.instrument_id_set:
            self.instrument_id_set[instrument] = set()
        self.instrument_id_set[instrument].add(stockcode)

    def _lookup_ss_id(self, id_: str | int) -> pd.Series:
        return self.ss_id_df.loc[int(id_)]

    def rm_short_item(self, stockcode: str, size: int = 0) -> float:
        stockcode = str(stockcode)
        instrument = self._lookup_ss_id(stockcode)["instrument"]
        if size == 0 and stockcode in self.size:
            size = self.size[stockcode]
            self.size.pop(stockcode)
            self.money.pop(stockcode)
            self.instrument_id_set[instrument].remove(stockcode)
            if len(self.instrument_id_set[instrument]) == 0:
                self.instrument_id_set.pop(instrument)
        elif stockcode in self.size:
            self.size[stockcode] -= size
            self.money[stockcode] = self.size[stockcode] * self.open_price[stockcode]
            if self.size[stockcode] <= 0:
                self.size.pop(stockcode)
                self.money.pop(stockcode)
                self.instrument_id_set[instrument].remove(stockcode)
                if len(self.instrument_id_set[instrument]) == 0:
                    self.instrument_id_set.pop(instrument)
        return size * self.open_price[stockcode] * self.apply_rate[stockcode]

    def update_hold_days(self) -> None:
        for key in self.hold_days:
            self.hold_days[key] += 1

    def get_short_id_set_by_instrument(self, instrument: str) -> set[str]:
        return self.instrument_id_set.get(instrument, set()).copy()

    def add_long_item(self, stockcode: str, size: int, money: float, open_price: float) -> None:
        if stockcode in self.size:
            self.size[stockcode] += size
            self.money[stockcode] += money
            self.open_price[stockcode] = self.money[stockcode] / self.size[stockcode]
            return
        self.size[stockcode] = size
        self.money[stockcode] = money
        self.open_price[stockcode] = open_price
        self.hold_days[stockcode] = 1

    def rm_long_item(self, stockcode: str, size: int = 0) -> None:
        if size == 0 and stockcode in self.size:
            self.size.pop(stockcode)
            self.money.pop(stockcode)
            self.open_price.pop(stockcode)
            self.hold_days.pop(stockcode)
        elif stockcode in self.size:
            self.size[stockcode] -= size
            self.money[stockcode] = self.size[stockcode] * self.open_price[stockcode]
            if self.size[stockcode] <= 0:
                self.size.pop(stockcode)
                self.money.pop(stockcode)
                self.open_price.pop(stockcode)
                self.hold_days.pop(stockcode)

    def get_short_position(
        self,
        dt: datetime,
        dt_next: datetime,
        dt_next_next: datetime,
    ) -> tuple[pd.DataFrame, list[str], list[str]]:
        if not self.size:
            return pd.DataFrame(columns=["stockcode", "volume"]), [], []

        res = pd.DataFrame.from_dict(self.size, orient="index")
        res = res.reset_index()
        res.columns = ["stockcode", "volume"]
        res = res[~res["stockcode"].str.contains("S").fillna(False)]
        res["instrument"] = res["stockcode"].apply(lambda x: self._lookup_ss_id(x)["instrument"])
        res["close"] = res["instrument"].apply(lambda x: get_none_close(dt, x))
        res["hold_days"] = res["stockcode"].apply(lambda x: self.hold_days[x])
        res["apply_rate"] = res["stockcode"].apply(
            lambda x: self.apply_rate[x] * self.open_price[x] * (dt_next_next - dt_next).days
        )
        res.drop(columns=["instrument"], inplace=True)

        return res, [], []

    def get_long_position(
        self,
        dt: datetime,
        dt_next: datetime | None = None,
    ) -> tuple[pd.DataFrame, list[str]]:
        if not self.size:
            return pd.DataFrame(
                columns=["stockcode", "volume", "close", "hold_days", "apply_rate"]
            ), []

        res = pd.DataFrame.from_dict(self.size, orient="index")
        res = res.reset_index()
        res.columns = ["stockcode", "volume"]
        res = res[res["stockcode"].str.contains("S").fillna(False)]

        if not res.empty:
            res["close"] = res["stockcode"].apply(lambda x: get_none_close(dt, x))
            res["hold_days"] = res["stockcode"].apply(lambda x: self.hold_days[x])
            res["apply_rate"] = 0.0
        else:
            res = pd.DataFrame(columns=["stockcode", "volume", "close", "hold_days", "apply_rate"])

        return res, []

    def get_position(
        self,
        dt: datetime,
        dt_next: datetime,
        dt_next_next: datetime,
    ) -> tuple[pd.DataFrame, list[str], list[str]]:
        long_pos, delisted_stocks = self.get_long_position(dt, dt_next)
        short_pos, delisted_stocks2, delisted_bondid = self.get_short_position(
            dt, dt_next, dt_next_next
        )
        res = pd.concat([long_pos, short_pos])
        return res, delisted_stocks + delisted_stocks2, delisted_bondid

    def get_size(self, stockcode: str) -> int:
        return self.size.get(str(stockcode), 0)

    def safe_get_size(self, stockcode: str) -> int:
        return self.size.get(str(stockcode), 0)


__all__ = ["SizeRecorder", "LongShortSizeRecorder"]
