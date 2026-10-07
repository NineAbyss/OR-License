
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = REPO_ROOT / "datasets/portfolio_offline"
PACK_TIME_BASIS = "signal_close_execution_suspend_v1"

INDUSTRY_FACTORS = (
    "银行",
    "计算机",
    "环保",
    "商贸零售",
    "电力设备",
    "建筑装饰",
    "建筑材料",
    "农林牧渔",
    "电子",
    "交通运输",
    "汽车",
    "纺织服饰",
    "医药生物",
    "房地产",
    "通信",
    "公用事业",
    "综合",
    "机械设备",
    "石油石化",
    "有色金属",
    "传媒",
    "家用电器",
    "基础化工",
    "非银金融",
    "社会服务",
    "轻工制造",
    "国防军工",
    "美容护理",
    "煤炭",
    "食品饮料",
    "钢铁",
)


def configure_offline_env() -> None:
    src = BUNDLE_ROOT / "src"
    os.environ["QUANT_PRO_SNAPSHOT_MODE"] = "replay"
    os.environ["QUANT_PRO_OFFLINE_ONLY"] = "1"
    os.environ["QUANT_PRO_SNAPSHOT_DIR"] = str(BUNDLE_ROOT / "data/snapshot")
    os.environ["QUANT_PRO_FACTOR_SNAPSHOT_DIR"] = str(
        BUNDLE_ROOT / "data/snapshot/factors"
    )
    os.environ["QUANT_PRO_CALENDAR_FILE"] = str(
        BUNDLE_ROOT / "data/snapshot/calendar.csv"
    )
    os.environ["QUANT_PRO_RISK_COVARIANCE_DIR"] = str(
        BUNDLE_ROOT / "data/risk_factor_covariance"
    )
    import sys

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _round_list(values: np.ndarray, digits: int) -> list[float]:
    return [round(float(value), digits) for value in np.asarray(values, dtype=float)]


def _round_matrix(matrix: np.ndarray, digits: int) -> list[list[float]]:
    return [_round_list(row, digits) for row in np.asarray(matrix, dtype=float)]


def load_scores(path: Path, date: str) -> pd.Series:
    frame = pd.read_feather(path)
    stamp = pd.Timestamp(date)
    picked = frame.loc[pd.to_datetime(frame["datetime"]) == stamp, ["instrument", "score"]]
    picked = picked.drop_duplicates("instrument", keep="first")
    series = pd.to_numeric(picked.set_index("instrument")["score"], errors="coerce")
    series.index = series.index.map(str)
    return series.dropna()


def execution_day(date: str) -> str:
    sessions = pd.to_datetime(
        pd.read_csv(BUNDLE_ROOT / "data/snapshot/calendar.csv")["date"]
    ).drop_duplicates().sort_values()
    signal = pd.Timestamp(date)
    if not sessions.eq(signal).any():
        raise ValueError(f"signal date is not in the trading calendar: {date}")
    later = sessions[sessions > signal]
    if later.empty:
        raise ValueError(f"no execution trading day after {date}")
    return later.iloc[0].strftime("%Y-%m-%d")


def load_market_day(date: str, benchmark_id: str) -> dict[str, Any]:
    suspension_date = execution_day(date)
    configure_offline_env()
    from quant_pro.infrastructure.clickhouse.data_fetcher_facade import (
        ClickHouseDataFetcher,
    )
    from quant_pro.infrastructure.clickhouse.snapshot_client import (
        SnapshotClickHouseClient,
    )

    fetcher = ClickHouseDataFetcher(SnapshotClickHouseClient())
    close = fetcher.get_close_price(date).copy()
    close["instrument"] = close["instrument"].map(str)
    close = close.drop_duplicates("instrument", keep="first").set_index("instrument")

    exposure = fetcher.get_factor_exposure(date).copy()
    exposure.index = exposure.index.map(str)
    covariance = fetcher.get_factor_covariance(date).copy()
    covariance.index = covariance.index.map(str)
    covariance.columns = covariance.columns.map(str)

    specific = fetcher.get_specific_risk(date).copy()
    specific.index = specific.index.map(str)
    sigma = pd.to_numeric(specific.iloc[:, 0], errors="coerce")

    weights = fetcher.get_index_weight(date, benchmark_id).copy()
    weights["instrument"] = weights["instrument"].map(str)
    bench = (
        pd.to_numeric(weights.drop_duplicates("instrument", keep="first")
        .set_index("instrument")["weight"], errors="coerce")
        .dropna()
    )

    constituents = {str(item) for item in fetcher.get_index_component(date, benchmark_id)}
    suspended = {str(item) for item in fetcher.get_suspend_stocks(suspension_date)}
    pt = fetcher.get_pt_stock(date)
    pt_stocks = set(pt["instrument"].map(str)) if "instrument" in pt else set()
    delisted = {
        str(instrument)
        for instrument, row in close.iterrows()
        if bool(row.get("is_delisted", False))
    }
    return {
        "signal_date": date,
        "execution_date": suspension_date,
        "close": close,
        "exposure": exposure,
        "covariance": covariance,
        "specific_sigma": sigma,
        "benchmark_weight": bench,
        "constituents": constituents,
        "suspended": suspended,
        "pt_stocks": pt_stocks,
        "delisted": delisted,
    }


def align_universe(
    *,
    scores: pd.Series,
    market: dict[str, Any],
    extra_keep: set[str] | None = None,
    keep_untradable: bool = False,
    include_constituents: bool = True,
) -> dict[str, Any]:
    close: pd.DataFrame = market["close"]
    exposure: pd.DataFrame = market["exposure"]
    covariance: pd.DataFrame = market["covariance"]
    sigma: pd.Series = market["specific_sigma"]
    bench: pd.Series = market["benchmark_weight"]
    constituents: set[str] = set(market["constituents"])
    suspended: set[str] = set(market["suspended"])
    if "pt_stocks" in market:
        pt_stocks: set[str] = set(market["pt_stocks"])
    else:
        pt_stocks = (
            {str(asset) for asset in close.index if bool(close.at[asset, "is_st"])}
            if "is_st" in close.columns else set()
        )
    if "delisted" in market:
        delisted: set[str] = set(market["delisted"])
    else:
        delisted = (
            {str(asset) for asset in close.index if bool(close.at[asset, "is_delisted"])}
            if "is_delisted" in close.columns else set()
        )

    factor_names = [
        name
        for name in covariance.columns
        if name in covariance.index and name in exposure.columns
    ]
    if not factor_names:
        raise RuntimeError("no common Barra factors")
    cov = (
        covariance.loc[factor_names, factor_names]
        .apply(pd.to_numeric, errors="coerce")
        .to_numpy(dtype=float)
    )
    cov = np.nan_to_num((cov + cov.T) / 2.0, nan=0.0, posinf=0.0, neginf=0.0)
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(eigvals, 0.0, None)
    cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
    cov = (cov + cov.T) / 2.0

    keep = set(scores.index)
    if include_constituents:
        keep |= set(constituents)
    if extra_keep:
        keep |= extra_keep
    assets: list[str] = []
    for asset in sorted(keep):
        if asset in suspended and not keep_untradable:
            continue
        if asset not in close.index or asset not in exposure.index or asset not in sigma.index:
            continue
        price = float(pd.to_numeric(close.at[asset, "close"], errors="coerce"))
        spec = float(sigma.at[asset])
        if not np.isfinite(price) or price <= 0 or not np.isfinite(spec) or spec < 0:
            continue
        row = pd.to_numeric(exposure.loc[asset, factor_names], errors="coerce").to_numpy(
            dtype=float
        )
        if not np.isfinite(row).all():
            continue
        if not keep_untradable and (
            bool(close.at[asset, "is_st"]) or bool(close.at[asset, "is_delisted"])
        ):
            continue
        assets.append(asset)
    if not assets:
        raise RuntimeError("empty aligned universe")

    exposures = np.vstack(
        [
            pd.to_numeric(exposure.loc[asset, factor_names], errors="coerce").to_numpy(
                dtype=float
            )
            for asset in assets
        ]
    )
    style_factors = [name for name in factor_names if name not in INDUSTRY_FACTORS]
    industry_factors = [name for name in factor_names if name in INDUSTRY_FACTORS]
    core = []
    for asset in assets:
        flags = close.loc[asset]
        core.append(
            bool(flags.get("is_300"))
            or bool(flags.get("is_500"))
            or bool(flags.get("is_1000"))
        )
    lot_shares = [200 if asset[2:4] == "68" else 100 for asset in assets]
    benchmark_weight = np.array(
        [float(bench.get(asset, 0.0)) for asset in assets], dtype=float
    )
    bench_sum = float(benchmark_weight.sum())
    if bench_sum > 0:
        benchmark_weight = benchmark_weight / bench_sum
    return {
        "asset_ids": assets,
        "score": np.array([float(scores.get(asset, 0.0)) for asset in assets], dtype=float),
        "benchmark_weight": benchmark_weight,
        "is_constituent": [asset in constituents for asset in assets],
        "is_core_index": core,
        "score_available": [asset in scores.index for asset in assets],
        "is_st": [asset in pt_stocks for asset in assets],
        "is_delisted": [asset in delisted for asset in assets],
        "is_tradable": [
            asset not in suspended
            and asset not in pt_stocks
            and asset not in delisted
            for asset in assets
        ],
        "is_suspended": [asset in suspended for asset in assets],
        "close": np.array(
            [float(close.at[asset, "close"]) for asset in assets], dtype=float
        ),
        "specific_variance": np.array(
            [float(sigma.at[asset]) ** 2 for asset in assets], dtype=float
        ),
        "lot_shares": lot_shares,
        "factor_names": factor_names,
        "style_factors": style_factors,
        "industry_factors": industry_factors,
        "exposures": exposures,
        "factor_covariance": cov,
        "close_frame": close,
    }


def fee_day_span(date: str, calendar: list[str] | None = None) -> int:
    if not calendar:
        path = BUNDLE_ROOT / "data/snapshot/calendar.csv"
        if not path.exists():
            return 1
        calendar = [
            str(value)[:10]
            for value in pd.read_csv(path)["date"].tolist()
        ]
    days = [day for day in calendar if day > date]
    if len(days) < 2:
        return 1
    next_day = pd.Timestamp(days[0])
    next_next = pd.Timestamp(days[1])
    return int((next_next - next_day).days) + 1


def load_borrow_capacity(
    date: str,
    assets: list[str],
    close: np.ndarray,
    portfolio_value: float,
    *,
    day_span: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    bonds = pd.read_csv(BUNDLE_ROOT / "data/market/merged_bonds_240301_251225.csv")
    day = bonds.loc[bonds["cre_time"].astype(str).str.startswith(date)].copy()
    day["instrument"] = day["instrument"].map(str)
    day["available"] = pd.to_numeric(day["available"], errors="coerce").fillna(0.0)
    day["apply_rate"] = pd.to_numeric(day["apply_rate"], errors="coerce")
    span = int(day_span) if day_span is not None else fee_day_span(date)
    capacity = np.zeros(len(assets), dtype=float)
    fee = np.zeros(len(assets), dtype=float)
    grouped = day.groupby("instrument")
    index = {asset: i for i, asset in enumerate(assets)}
    for instrument, group in grouped:
        if instrument not in index:
            continue
        i = index[instrument]
        shares = float(group["available"].sum())
        offered = group.loc[group["available"] > 0, "apply_rate"].dropna()
        capacity[i] = shares * float(close[i]) / float(portfolio_value)
        fee[i] = float(offered.min()) * span if not offered.empty else 0.0
    return capacity, fee


def tracking_error(
    active: np.ndarray,
    exposures: np.ndarray,
    covariance: np.ndarray,
    specific_variance: np.ndarray,
) -> float:
    factor_active = exposures.T @ active
    systematic = float(factor_active @ covariance @ factor_active)
    specific = float(np.dot(specific_variance, np.square(active)))
    value = systematic + specific
    return float(np.sqrt(max(value, 0.0)))


def active_exposures(
    weights: np.ndarray,
    benchmark: np.ndarray,
    exposures: np.ndarray,
) -> np.ndarray:
    return exposures.T @ (weights - benchmark)


def pack_common(aligned: dict[str, Any], *, score_digits: int = 6) -> dict[str, Any]:
    return {
        "asset_ids": aligned["asset_ids"],
        "score": _round_list(aligned["score"], score_digits),
        "benchmark_weight": _round_list(aligned["benchmark_weight"], 8),
        "is_constituent": [bool(flag) for flag in aligned["is_constituent"]],
        "previous_weight": [0.0] * len(aligned["asset_ids"]),
        "close": _round_list(aligned["close"], 6),
        "specific_variance": _round_list(aligned["specific_variance"], 10),
        "factor_names": list(aligned["factor_names"]),
        "style_factors": list(aligned["style_factors"]),
        "industry_factors": list(aligned["industry_factors"]),
        "exposures": _round_matrix(aligned["exposures"], 6),
        "factor_covariance": _round_matrix(aligned["factor_covariance"], 10),
    }
