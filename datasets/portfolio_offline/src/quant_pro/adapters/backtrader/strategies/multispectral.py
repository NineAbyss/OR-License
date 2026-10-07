
from __future__ import annotations

from quant_pro.adapters.backtrader.strategies.enhanced_index import (
    BT_EnhancedIndexStockSelectStrategy,
    EnhancedIndexStrategy,
)

MultiSpectralStrategy = EnhancedIndexStrategy
BT_MultiSpectralStockSelectStrategy = BT_EnhancedIndexStockSelectStrategy

__all__ = [
    "MultiSpectralStrategy",
    "BT_MultiSpectralStockSelectStrategy",
]
