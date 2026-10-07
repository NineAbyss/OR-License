
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pandas as pd

_RANGE = re.compile(
    r"(?:date\(datetime\)|datetime)\s*>=\s*'(?P<start>\d{4}-\d{2}-\d{2})'.*?"
    r"(?:date\(datetime\)|datetime)\s*<=\s*'(?P<end>\d{4}-\d{2}-\d{2})'",
    re.DOTALL,
)

_TABLES = (
    ("close, total_turnover, turnover", "period_close_turnover.parquet"),
    ("return AS specific_return", "specific_return_ts.parquet"),
    ("ods.ods_quant_stock_marketdata_factor_return_di", "factor_return_ts.parquet"),
    ("ods_quant_stock_marketdata_factor_exposure_di", "factor_exposure_ts.parquet"),
)


def query_canonical_range(sql: str) -> pd.DataFrame | None:
    match = _RANGE.search(sql)
    if match is None:
        return None
    filename = next((name for marker, name in _TABLES if marker in sql), None)
    if filename is None:
        return None
    configured = os.environ.get("QUANT_PRO_CANONICAL_RANGE_DIR")
    if configured:
        root = Path(configured)
    else:
        snapshot_root = os.environ.get("QUANT_PRO_SNAPSHOT_DIR")
        if not snapshot_root:
            return None
        root = Path(snapshot_root) / "canonical_range"
    path = root / filename
    if not path.exists():
        return None
    start = date.fromisoformat(match.group("start"))
    end = date.fromisoformat(match.group("end"))
    frame = pd.read_parquet(
        path,
        filters=[("datetime", ">=", start), ("datetime", "<=", end)],
    )
    sort_columns = [column for column in ("datetime", "instrument") if column in frame]
    if sort_columns:
        frame = frame.sort_values(sort_columns, kind="stable")
    return frame.reset_index(drop=True)


__all__ = ["query_canonical_range"]
