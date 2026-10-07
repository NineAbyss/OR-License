
from __future__ import annotations

from typing import Protocol


class TradingCalendarPort(Protocol):

    def next_trade_day(self, date: str, n: int = 1) -> str:
        ...

    def previous_trade_day(self, date: str, n: int = 1) -> str:
        ...
