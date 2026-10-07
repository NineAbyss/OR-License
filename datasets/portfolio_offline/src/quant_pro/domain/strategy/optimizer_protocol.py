
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class LongShortOptimizerProtocol(Protocol):

    def optimize(
        self,
        pred: pd.DataFrame,
        bond: pd.DataFrame | None,
        total_value: float,
        position: pd.DataFrame | None = None,
        short_whole_weight: float = 0.0,
        temp_path: str = "",
        **kwargs: object,
    ) -> pd.DataFrame:
        ...
