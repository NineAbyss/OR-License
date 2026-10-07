
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class DatabasePort(Protocol):

    def query(self, sql: str) -> pd.DataFrame:
        ...

    def _disconnect(self) -> None:
        ...

    def get_connect(self) -> Any:
        ...
