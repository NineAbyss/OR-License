
from __future__ import annotations

import backtrader as bt


class MyTimeReturn(bt.analyzers.TimeReturn):
    pass


class HedgingAnalyzer(bt.analyzers.PyFolio, metaclass=type(bt.analyzers.PyFolio)):

    def __init__(self) -> None:
        super().__init__()
        dtfcomp = {
            "timeframe": self.p.timeframe,
            "compression": self.p.compression,
        }
        self._returns = MyTimeReturn(**dtfcomp)


__all__ = ["HedgingAnalyzer", "MyTimeReturn"]
