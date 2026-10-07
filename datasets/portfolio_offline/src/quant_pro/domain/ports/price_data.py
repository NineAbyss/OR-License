
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PriceDataPort(Protocol):

    def load_factors(self, factors: Sequence[str]) -> None:
        ...

    def set_custom_open(self, factor_name: str) -> None:
        ...

    def set_custom_close(self, factor_name: str) -> None:
        ...
