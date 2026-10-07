
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from quant_pro.adapters.backtrader.strategies.single_sif_beta0_next_month import (
    SingleSIFBeta0NextMonthStrategy,
)
from quant_pro.application.config.single_sif_beta0_next_month import (
    load_single_sif_beta0_next_month_config,
)
from quant_pro.application.optimization.score_inputs import (
    infer_period_num_from_tuning_params,
    load_score_pivots,
    pivot_date_bounds,
    union_pivot_instruments,
)
from quant_pro.infrastructure.offline_neutral_data import (
    HybridOfflineNeutralDataFetcher,
    WideParquetICFutureData,
    WideParquetTradingCalendar,
)
from quant_pro.infrastructure.exposure.exposure_analyzer import (
    DEFAULT_INDUSTRY_FACTORS,
)

logger = logging.getLogger(__name__)

BUNDLE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = BUNDLE_ROOT / "data" / "offline_20240301_20251225"
DEFAULT_SCORE = (
    BUNDLE_ROOT
    / "data"
    / "scores"
    / "xgb_rolling_comb_neu500_21_static_daily.feather"
)
DEFAULT_TUNING_PARAMS = (
    BUNDLE_ROOT / "configs" / "optimizers" / "single_sif_beta0_next_month.yaml"
)
DEFAULT_FRAMEWORK_CONFIG = BUNDLE_ROOT / "config.yaml"
DEFAULT_INITIAL_ID = "SingleSIFBeta0NextMonthInitialOptimizer1"
DEFAULT_REBALANCE_ID = "SingleSIFBeta0NextMonthRebalanceOptimizer1"

_COMPONENT_INDICES = ("IN000300", "IN000905", "IN000852", "IN000922", "IN932000")
_STOCK_FEED_FACTORS = (
    "close",
    "open",
    "high",
    "low",
    "volume",
    "total_turnover",
    "open_up_limit",
    "open_down_limit",
    "factor",
    "reach_limit_up_in_5",
    "reach_limit_down_in_5",
    "rank_cap",
    "rank_vol",
    "rank_amount",
    "rank_turnover",
    "rank_amihud",
    "rank_bid_ask_spread_01",
    "rank_bid_ask_spread_05",
    "rank_bid_ask_spread_10",
    "rank_bid_ask_spread_all",
    "rank_sellvol",
    "rank_buyvol",
    "rank_sellcount",
    "rank_buycount",
    "rank_allcount",
    "is_event_accepted_v2",
)


def configure_offline_environment(data_root: str | Path) -> dict[str, Path]:

    root = Path(data_root).resolve()
    paths = {
        "root": root,
        "snapshot": root / "snapshot",
        "factors": root / "snapshot" / "factors",
        "calendar": root / "snapshot" / "calendar.csv",
        "risk": root / "risk_factor_covariance",
    }
    os.environ["QUANT_PRO_SNAPSHOT_MODE"] = "replay"
    os.environ["QUANT_PRO_SNAPSHOT_DIR"] = str(paths["snapshot"])
    os.environ["QUANT_PRO_FACTOR_SNAPSHOT_DIR"] = str(paths["factors"])
    os.environ["QUANT_PRO_CALENDAR_FILE"] = str(paths["calendar"])
    os.environ["QUANT_PRO_RISK_COVARIANCE_DIR"] = str(paths["risk"])
    return paths


def _require_file(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"offline {label} missing or empty: {path}")


def _require_fresh_persist_path(persist_path: str | Path) -> None:

    if not persist_path:
        return
    state_file = Path(persist_path) / "dailyhigh_neutral_state.json"
    if state_file.exists():
        raise FileExistsError(
            "single_SIF_beta0_next_month only supports fresh offline runs; "
            f"existing state must not be reused: {state_file}"
        )


def _require_industry_factors(
    industries: list[str], *, exposure_columns: Any | None = None
) -> list[str]:

    normalized = list(dict.fromkeys(str(item) for item in industries if str(item)))
    if not normalized:
        raise ValueError(
            "single_SIF_beta0_next_month requires a non-empty framework "
            "industry-factor list"
        )
    configured = set(normalized)
    expected = set(DEFAULT_INDUSTRY_FACTORS)
    if configured != expected:
        raise ValueError(
            "single_SIF_beta0_next_month industry factors must exactly match "
            "ExposureAnalyzer.DEFAULT_INDUSTRY_FACTORS; "
            f"missing={sorted(expected - configured)}, "
            f"unexpected={sorted(configured - expected)}"
        )
    if exposure_columns is not None:
        available = {str(item) for item in exposure_columns}
        missing = sorted(set(normalized) - available)
        if missing:
            raise ValueError(
                "configured industry factors are absent from offline factor exposure: "
                f"{missing}"
            )
    return normalized


def _decision_dates(
    calendar: WideParquetTradingCalendar, start_date: Any, end_date: Any
) -> list[pd.Timestamp]:
    start, end = pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize()
    result = list(calendar.dates[(calendar.dates >= start) & (calendar.dates <= end)])
    if not result or result[0] != start or result[-1] != end:
        raise ValueError(f"offline calendar does not cover decision window {start.date()} .. {end.date()}")
    return result


def preflight_offline_bundle(
    *,
    data_root: str | Path,
    score_path: str | Path,
    tuning_params_path: str | Path,
    start_date: Any,
    end_date: Any,
    tuning_params_list: list[dict[str, Any]] | None = None,
    verify_replay_calls: bool = True,
) -> dict[str, Any]:

    paths = configure_offline_environment(data_root)
    _require_file(Path(score_path), "score")
    _require_file(Path(tuning_params_path), "optimizer config")
    _require_file(paths["calendar"], "calendar")
    _require_file(paths["snapshot"] / "clickhouse_queries" / "index.json", "SQL manifest")
    _require_file(
        paths["snapshot"] / "optimizer_fetcher_calls" / "index.json",
        "optimizer-call manifest",
    )
    for factor in _STOCK_FEED_FACTORS:
        _require_file(paths["factors"] / "day" / f"{factor}.parquet", f"day/{factor}")

    params = tuning_params_list or load_single_sif_beta0_next_month_config(tuning_params_path)
    calendar = WideParquetTradingCalendar(paths["calendar"])
    dates = _decision_dates(calendar, start_date, end_date)
    execution_end = pd.Timestamp(calendar.next_trade_day(str(dates[-1].date())))
    future_data = WideParquetICFutureData(paths["factors"])
    frames, _ = future_data.load_feed_frames(
        family="IC", start_date=dates[0], end_date=execution_end
    )

    history_days = max(int(stage.get("history_days", 100)) for stage in params)
    history_start = calendar.previous_trade_day(str(dates[0].date()), history_days)
    fetcher = HybridOfflineNeutralDataFetcher(paths["factors"])
    fetcher.get_period_close_turnover(history_start, str(dates[-1].date()))

    if verify_replay_calls:
        for decision_date in dates:
            date_text = decision_date.strftime("%Y-%m-%d")
            next_text = calendar.next_trade_day(date_text)
            fetcher.get_close_price(date_text)
            fetcher.cal_idx_return(date_text, "IN000905")
            fetcher.get_factor_exposure(date_text)
            fetcher.get_factor_exposure_today(date_text)
            fetcher.get_specific_risk(date_text)
            for index_code in _COMPONENT_INDICES:
                fetcher.get_index_weight(date_text, index_code)
                fetcher.get_index_component(date_text, index_code)
            fetcher.get_factor_covariance(date_text)
            fetcher.get_pt_stock(date_text)
            fetcher.get_suspend_stocks(next_text)
            future_data.get_all_index_close_prices(date_text, ["IN399905"])
            future_data.get_all_future_close_prices(date_text, ["IC"])
            future_data.get_future_delisted_dates(date_text, ["IC"])
            future_data.get_future_volume_interest_multiplier(date_text, ["IC"])
            future_data.get_allocation_margin_rate(next_text, "IC")

    return {
        "start_date": dates[0].strftime("%Y-%m-%d"),
        "end_date": dates[-1].strftime("%Y-%m-%d"),
        "execution_end": execution_end.strftime("%Y-%m-%d"),
        "decision_days": len(dates),
        "history_start": history_start,
        "future_contracts": sorted(frames),
        "stages": len(params),
    }


def register_optimizers(
    *,
    data_fetcher: HybridOfflineNeutralDataFetcher,
    future_data: WideParquetICFutureData,
    calendar: WideParquetTradingCalendar,
    tuning_params_list: list[dict[str, Any]],
    industries: list[str],
    initial_id: str,
    rebalance_id: str,
) -> tuple[Any, Any]:

    raise RuntimeError("A submitted solver must be installed through run_delegated")


def run_backtest(
    *,
    score_source: Any = DEFAULT_SCORE,
    tuning_params_path: str | Path = DEFAULT_TUNING_PARAMS,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    framework_config_path: str | Path = DEFAULT_FRAMEWORK_CONFIG,
    start_date: str | None = None,
    end_date: str | None = None,
    cash: float = 30_000_000.0,
    persist_path: str = "",
    initial_optimizer_id: str = DEFAULT_INITIAL_ID,
    rebalance_optimizer_id: str = DEFAULT_REBALANCE_ID,
    skip_preflight: bool = False,
) -> list[Any]:

    paths = configure_offline_environment(data_root)
    _require_fresh_persist_path(persist_path)
    tuning_params_list = load_single_sif_beta0_next_month_config(tuning_params_path)
    period_num = infer_period_num_from_tuning_params(tuning_params_list)
    pivots = load_score_pivots(score_source, period_num=period_num)
    if not pivots:
        raise ValueError("single_SIF_beta0_next_month score source produced no frames")
    inferred_start, inferred_end = pivot_date_bounds(pivots)
    start = pd.Timestamp(start_date) if start_date else inferred_start
    end = pd.Timestamp(end_date) if end_date else inferred_end
    if pd.isna(start) or pd.isna(end) or end < start:
        raise ValueError(f"invalid backtest range: {start} .. {end}")
    if start < inferred_start or end > inferred_end:
        raise ValueError(
            "requested backtest window is outside score coverage: "
            f"requested={start.date()}..{end.date()}, "
            f"coverage={inferred_start.date()}..{inferred_end.date()}"
        )
    signal_dates = {
        pd.Timestamp(value).normalize()
        for pivot in pivots
        for value in pivot.index
        if start.normalize() <= pd.Timestamp(value).normalize() <= end.normalize()
    }
    if not signal_dates:
        raise ValueError(
            f"requested backtest window {start.date()}..{end.date()} contains no score signal"
        )

    if not skip_preflight:
        preflight_offline_bundle(
            data_root=data_root,
            score_path=score_source,
            tuning_params_path=tuning_params_path,
            start_date=start,
            end_date=end,
            tuning_params_list=tuning_params_list,
        )

    from quant_pro.adapters.backtrader.data_feed import (
        ENHANCED_INDEX_FACTORS,
        init_cerebro_data,
        lazy_load_market_data,
    )
    from quant_pro.entry.future_execution import (
        add_future_feeds,
        validate_stock_factor_snapshot,
    )
    from quant_pro.infrastructure.config import load_yaml_with_env

    calendar = WideParquetTradingCalendar(paths["calendar"])
    execution_end = pd.Timestamp(calendar.next_trade_day(end.strftime("%Y-%m-%d")))
    future_data = WideParquetICFutureData(paths["factors"])
    data_fetcher = HybridOfflineNeutralDataFetcher(paths["factors"])
    config = load_yaml_with_env(str(framework_config_path), strict=False)
    industries = list(
        config.get("portfolio_optimizers", {}).get("shared_data", {}).get("industries", [])
    )
    exposure_columns = data_fetcher.get_factor_exposure(
        start.strftime("%Y-%m-%d")
    ).columns
    industries = _require_industry_factors(
        industries, exposure_columns=exposure_columns
    )
    register_optimizers(
        data_fetcher=data_fetcher,
        future_data=future_data,
        calendar=calendar,
        tuning_params_list=tuning_params_list,
        industries=industries,
        initial_id=initial_optimizer_id,
        rebalance_id=rebalance_optimizer_id,
    )

    market_data = lazy_load_market_data(
        limit_start=start,
        limit_end=execution_end,
        factors=ENHANCED_INDEX_FACTORS,
    )
    validate_stock_factor_snapshot(market_data, start_date=start, end_date=execution_end)
    cerebro = init_cerebro_data(
        instruments=union_pivot_instruments(pivots),
        start_date=start,
        end_date=execution_end,
        market_data=market_data,
        broker_cls=None,
        cash=cash,
        commission=0.00045,
        slippage_perc=0.0003,
        configure_futures=False,
    )
    future_frames, future_info = future_data.load_feed_frames(
        family="IC", start_date=start, end_date=execution_end
    )
    add_future_feeds(cerebro, future_frames, future_info)
    cerebro.addstrategy(
        SingleSIFBeta0NextMonthStrategy,
        weight=pivots,
        tuning_params_list=tuning_params_list,
        initial_optimizer_instance_id=initial_optimizer_id,
        rebalance_optimizer_instance_id=rebalance_optimizer_id,
        persist_path=persist_path,
        margin_rate_provider=future_data,
    )
    result = cerebro.run()
    candidates = [
        item
        for outer in result
        for item in (outer if isinstance(outer, (list, tuple)) else [outer])
    ]
    strategies = [item for item in candidates if hasattr(item, "_initialized")]
    if not strategies:
        raise RuntimeError("backtest returned no inspectable next-month strategy instance")
    failures: list[str] = []
    for strategy in strategies:
        if not bool(getattr(strategy, "_initialized", False)):
            failures.append("strategy was never initialized")
        status = getattr(strategy, "_transition_status", None)
        if status is not None:
            failures.append(f"transition_status={status!r}")
        pending = getattr(strategy, "_pending_transition_orders", {})
        compensation = getattr(strategy, "_compensation_orders", {})
        snapshot = getattr(strategy, "_transition_snapshot", None)
        if pending:
            failures.append(f"pending_order_refs={sorted(pending)}")
        if compensation:
            failures.append(f"compensation_order_refs={sorted(compensation)}")
        if snapshot is not None:
            failures.append("transition snapshot remains unfinished")
    if failures:
        raise RuntimeError("next-month backtest terminal validation failed: " + "; ".join(failures))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pure-offline IC next-month neutral backtest")
    parser.add_argument("--score", default=str(DEFAULT_SCORE))
    parser.add_argument("--tuning-params", default=str(DEFAULT_TUNING_PARAMS))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--framework-config", default=str(DEFAULT_FRAMEWORK_CONFIG))
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--cash", type=float, default=30_000_000.0)
    parser.add_argument("--persist-path", default="")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper()))
    run_backtest(
        score_source=args.score,
        tuning_params_path=args.tuning_params,
        data_root=args.data_root,
        framework_config_path=args.framework_config,
        start_date=args.start_date,
        end_date=args.end_date,
        cash=args.cash,
        persist_path=args.persist_path,
        skip_preflight=args.skip_preflight,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
