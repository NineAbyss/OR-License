
from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_score_data(weight: pd.DataFrame | None) -> pd.DataFrame:
    if weight is None or weight.empty:
        return pd.DataFrame(columns=["datetime", "instrument", "score"])

    w = weight.copy()

    if not np.issubdtype(w.index.dtype, np.datetime64):
        w.index = pd.to_datetime(w.index, errors="coerce")

    w = w.reset_index()
    idx_col = w.columns[0]
    if idx_col != "datetime":
        w = w.rename(columns={idx_col: "datetime"})
    df = w.melt(id_vars=["datetime"], var_name="instrument", value_name="score").dropna(
        subset=["score"]
    )

    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d")

    if df["instrument"].dtype != object:
        df["instrument"] = df["instrument"].astype(str)

    return df[["datetime", "instrument", "score"]]
