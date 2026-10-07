
from __future__ import annotations

import argparse
import logging
import os
from typing import Any

import numpy as np
import pandas as pd
import yaml

from quant_pro.application.optimization.score_inputs import (
    apply_score_path_auto_default,
    apply_score_period_auto_metadata,
    infer_period_num_from_tuning_params,
    load_score_frames,
    pivot_date_bounds,
    score_frames_to_pivots,
    union_pivot_instruments,
)
from quant_pro.entry._config_path import (
    default_backtest_config_path,
    sync_backtester_config,
)
from quant_pro.infrastructure.config import load_yaml_with_env

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

logger = logging.getLogger(__name__)

_ORDINAL_STAGE_KEYS = {"first", "second", "third", "fourth", "fifth", "sixth"}
_FLAT_TUNING_MARKER_KEYS = {
    "benchmark",
    "components",
    "constraints",
    "controls",
    "lowerbounds",
    "multiperiod",
    "multiperiod_params",
    "upperbounds",
}


def _normalize_tuning_params(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [tp for tp in raw if isinstance(tp, dict)]
    if not isinstance(raw, dict):
        return []

    raw_keys = set(raw)
    if _ORDINAL_STAGE_KEYS & raw_keys:
        return [tp for tp in raw.values() if isinstance(tp, dict)]
    if _FLAT_TUNING_MARKER_KEYS & raw_keys:
        return [raw]

    named_configs = [tp for tp in raw.values() if isinstance(tp, dict)]
    return named_configs or [raw]


def _default_daily_state_path(
    save_daily_state: bool,
    daily_state_path: str | None,
    output_dir: str | None,
) -> str | None:
    if save_daily_state and daily_state_path is None and output_dir:
        return os.path.join(output_dir, "incremental")
    return daily_state_path


def main() -> None:
    parser = argparse.ArgumentParser(description="LongShort standalone backtest")
    parser.add_argument(
        "--weight_path",
        default=os.environ.get("QUANT_PRO_SCORE_PATH"),
        required=os.environ.get("QUANT_PRO_SCORE_PATH") is None,
        help="Path to scores .feather file (env: QUANT_PRO_SCORE_PATH)",
    )
    parser.add_argument(
        "--output_dir",
        default=os.environ.get("QUANT_PRO_OUTPUT_DIR"),
        required=os.environ.get("QUANT_PRO_OUTPUT_DIR") is None,
        help="Output directory (env: QUANT_PRO_OUTPUT_DIR)",
    )
    parser.add_argument(
        "--tuning_params",
        default=os.environ.get("QUANT_PRO_TUNING_PARAMS"),
        required=os.environ.get("QUANT_PRO_TUNING_PARAMS") is None,
        help="Path to tuning_params YAML (env: QUANT_PRO_TUNING_PARAMS)",
    )
    parser.add_argument(
        "--config_path",
        default=default_backtest_config_path(),
        help="Optimizer config.yaml (env: QUANT_PRO_DB_CONFIG)",
    )
    parser.add_argument("--slips_path", default=None, help="Path to borrow slips CSV")
    parser.add_argument("--initial_optimizer_id", default="NewLongShortInitialOptimizer1")
    parser.add_argument("--rebalance_optimizer_id", default="NewLongShortRebalanceOptimizer1")
    parser.add_argument(
        "--optimizer-backend",
        choices=["mosek-continuous", "gurobi-mip-soc", "gurobi-soc-relax"],
        default="mosek-continuous",
        help=(
            "Optimizer formulation. 'gurobi-mip-soc' keeps the legacy flex-filter "
            "binary variables; 'gurobi-soc-relax' uses quant_pro-style direct "
            "continuous long/short weights. Both add the Barra volatility cone "
            "and objective penalty."
        ),
    )
    parser.add_argument(
        "--volatility-upper-bound",
        type=float,
        default=float(os.environ.get("QUANT_PRO_GUROBI_VOL_UB", "0.05")),
        help=(
            "Annualized Barra volatility upper bound for gurobi-mip-soc "
            "(default: 0.05, i.e. 5%%)."
        ),
    )
    parser.add_argument(
        "--volatility-penalty-lambda",
        type=float,
        default=float(os.environ.get("QUANT_PRO_GUROBI_VOL_LAMBDA", "0.05")),
        help=(
            "MOSEK-compatible objective penalty on annualized Barra volatility "
            "for gurobi-mip-soc (default: 0.05)."
        ),
    )
    parser.add_argument(
        "--gurobi-time-limit",
        type=float,
        default=float(os.environ.get("QUANT_PRO_GUROBI_TIME_LIMIT", "3600")),
        help="Per-solve Gurobi time limit in seconds (default: 3600).",
    )
    parser.add_argument(
        "--gurobi-threads",
        type=int,
        default=int(os.environ.get("QUANT_PRO_GUROBI_THREADS", "0")),
        help="Gurobi thread count; 0 lets Gurobi use all logical processors.",
    )
    parser.add_argument(
        "--gurobi-mip-gap",
        type=float,
        default=float(os.environ.get("QUANT_PRO_GUROBI_MIP_GAP", "0.01")),
        help="Relative MIP optimality gap (default: 0.01, matching legacy flex-filter).",
    )
    parser.add_argument(
        "--gurobi-acceptable-mip-gap",
        type=float,
        default=(
            float(os.environ["QUANT_PRO_GUROBI_ACCEPTABLE_MIP_GAP"])
            if "QUANT_PRO_GUROBI_ACCEPTABLE_MIP_GAP" in os.environ
            else None
        ),
        help=(
            "Accept a Gurobi integer MIP incumbent at TIME_LIMIT only when its "
            "relative gap is at most this value. Unset preserves strict status handling."
        ),
    )
    parser.add_argument(
        "--database_instance_id",
        default=os.environ.get("QUANT_PRO_DB_INSTANCE"),
        help=(
            "ClickHouse instance ID to use from config. "
            "Defaults: env QUANT_PRO_DB_INSTANCE, then canonical 'clickhouse4', "
            "then first available instance in the config yaml."
        ),
    )
    parser.add_argument("--holding_num", type=int, default=60)
    parser.add_argument("--rolling_num", type=int, default=7)
    parser.add_argument("--set_cash", type=float, default=10_000_000.0)
    parser.add_argument("--start_time", default=None)
    parser.add_argument("--end_time", default=None)
    parser.add_argument("--execution_end_time", default=None)
    parser.add_argument(
        "--vwapopen",
        default=None,
        help=(
            "Optional data_process factor name to use as the fill/valuation "
            "OPEN price instead of the default open (e.g. vwap_15min_0). The "
            "factor is loaded via load_factors and swapped into datas.day.open "
            "before cerebro feeds are built. Omit (default None) for "
            "byte-identical default-price behavior."
        ),
    )
    parser.add_argument(
        "--vwapclose",
        default=None,
        help=(
            "Optional data_process factor name to use as the fill/valuation "
            "CLOSE price instead of the default close (e.g. vwap_15min_0). The "
            "factor is loaded via load_factors and swapped into datas.day.close "
            "before cerebro feeds are built. Omit (default None) for "
            "byte-identical default-price behavior."
        ),
    )
    parser.add_argument(
        "--incremental_state_path",
        default=None,
        help="Path to a saved LS incremental state pickle for resume/live mode.",
    )
    parser.add_argument(
        "--save_daily_state",
        action="store_true",
        help="Save LS incremental state/order pickles at the end of each bar.",
    )
    parser.add_argument(
        "--daily_state_path",
        default=None,
        help="Directory for LS incremental state/order pickles.",
    )
    parser.add_argument(
        "--barra-config-file",
        default=None,
        help="Optional Barra attribution config override",
    )
    parser.add_argument(
        "--long-filter-pool-csv",
        dest="long_filter_pool_csv",
        default=None,
        help=(
            "Path to date-keyed long filter-pool CSV (columns: date, stock_code). "
            "Stocks listed for a given date are forbidden from LONG side that day. "
            "Default: None (no filter)."
        ),
    )
    parser.add_argument(
        "--short-filter-pool-csv",
        dest="short_filter_pool_csv",
        default=None,
        help=(
            "Path to date-keyed short filter-pool CSV (columns: date, stock_code). "
            "Stocks listed for a given date are forbidden from SHORT side that day. "
            "Default: None (no filter)."
        ),
    )
    parser.add_argument(
        "--no-prefetch-cache",
        dest="no_prefetch_cache",
        action="store_true",
        help=(
            "Disable the backtest read-through prefetch cache (default: cache "
            "ON for speed). The cache is provably ON==OFF byte-identical; this "
            "escape hatch reverts to the un-cached per-day query path. LIVE "
            "paths never use the cache regardless of this flag."
        ),
    )
    parser.add_argument(
        "--log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    args.config_path = sync_backtester_config(args.config_path)
    logger.info("LongShort standalone backtest starting")

    with open(args.tuning_params) as f:
        tuning_params_list = _normalize_tuning_params(yaml.safe_load(f))
    apply_score_path_auto_default(tuning_params_list, args.weight_path)
    apply_score_period_auto_metadata(tuning_params_list, args.weight_path)

    prefetch_enabled = not args.no_prefetch_cache
    gurobi_solver_params = {
        "TimeLimit": args.gurobi_time_limit,
        "Threads": args.gurobi_threads,
        "MIPGap": args.gurobi_mip_gap,
        "MIPGapAbs": 1e-4,
        "Presolve": 2,
        "Cuts": 2,
        "Heuristics": 0.1,
        "MIPFocus": 1,
        "Method": 2,
        "NodeMethod": 2,
        "BarHomogeneous": 1,
        "BarOrder": 1,
        "NumericFocus": 1,
    }
    if args.optimizer_backend == "gurobi-mip-soc":
        gurobi_solver_params.update(
            {
                "AcceptableMIPGap": args.gurobi_acceptable_mip_gap,
                "Method": 1,
                "NodeMethod": 1,
            }
        )
        gurobi_solver_params.pop("BarHomogeneous")
        gurobi_solver_params.pop("BarOrder")
    prefetch_fetcher, prefetch_calendar = _register_optimizers(
        args.config_path,
        tuning_params_list,
        args.initial_optimizer_id,
        args.rebalance_optimizer_id,
        args.database_instance_id,
        prefetch_enabled=prefetch_enabled,
        optimizer_backend=args.optimizer_backend,
        volatility_upper_bound=args.volatility_upper_bound,
        volatility_penalty_lambda=args.volatility_penalty_lambda,
        gurobi_solver_params=gurobi_solver_params,
    )

    from quant_pro.adapters.backtrader.data_feed import (
        LONGSHORT_FACTORS,
        lazy_load_market_data,
    )

    market_data = lazy_load_market_data(
        limit_start=args.start_time,
        limit_end=args.execution_end_time or args.end_time,
        factors=LONGSHORT_FACTORS,
    )

    from quant_pro.application.backtest.longshort_runner import _set_custom_price_data

    _set_custom_price_data(args.vwapopen, args.vwapclose)

    period_num = infer_period_num_from_tuning_params(tuning_params_list)
    score_frames = load_score_frames(args.weight_path, period_num=period_num)
    weight_pivots = score_frames_to_pivots(
        score_frames,
        start_time=args.start_time,
        end_time=args.end_time,
    )

    ss_df = _load_borrow_slips(args.slips_path)

    os.makedirs(args.output_dir, exist_ok=True)
    if weight_pivots:
        weight_pivots[0].to_csv(os.path.join(args.output_dir, "filter_weight.csv"))
        if len(weight_pivots) > 1:
            for idx, weight_pv in enumerate(weight_pivots):
                weight_pv.to_csv(os.path.join(args.output_dir, f"filter_weight_p{idx}.csv"))

    initial_position_file_path = os.path.join(args.output_dir, "initial_position.csv")

    state_manager = None
    daily_state_path = args.daily_state_path
    if args.incremental_state_path:
        from quant_pro.application.backtest.incremental_state import (
            IncrementalBacktestState,
            resolve_daily_state_path,
        )

        daily_state_path = resolve_daily_state_path(
            args.incremental_state_path,
            daily_state_path,
        )
        state_manager = IncrementalBacktestState(state_file_path=args.incremental_state_path)
        if not state_manager.load_from_file():
            raise FileNotFoundError(
                f"LS incremental state not found: {args.incremental_state_path}"
            )

    daily_state_path = _default_daily_state_path(
        args.save_daily_state, daily_state_path, args.output_dir
    )

    result = _run_backtest(
        weight=weight_pivots if len(weight_pivots) > 1 else weight_pivots[0],
        tuning_params_list=tuning_params_list,
        ss_df=ss_df,
        market_data=market_data,
        execution_end_date=args.execution_end_time,
        holding_num=args.holding_num,
        rolling_num=args.rolling_num,
        persist_path=args.output_dir,
        initial_optimizer_instance_id=args.initial_optimizer_id,
        rebalance_optimizer_instance_id=args.rebalance_optimizer_id,
        initial_position_file_path=initial_position_file_path,
        set_cash=args.set_cash,
        long_filter_pool_csv=args.long_filter_pool_csv,
        short_filter_pool_csv=args.short_filter_pool_csv,
        incremental_state_path=args.incremental_state_path,
        state_manager=state_manager,
        save_daily_state=args.save_daily_state,
        daily_state_path=daily_state_path,
        prefetch_fetcher=prefetch_fetcher if prefetch_enabled else None,
        prefetch_calendar=prefetch_calendar,
        benchmark=_ls_benchmark_from_tuning(tuning_params_list),
    )

    pyfolio = result[0].analyzers.pyfolio
    returns, positions, transactions, gross_lev = pyfolio.get_pf_items()

    returns.to_csv(os.path.join(args.output_dir, "returns.csv"))
    transactions.to_csv(os.path.join(args.output_dir, "transactions.csv"))
    positions.to_csv(os.path.join(args.output_dir, "positions.csv"))

    from quant_pro.application.backtest.longshort_runner import (
        save_daily_nav_and_returns,
    )

    save_daily_nav_and_returns(
        returns=returns,
        gross_lev=gross_lev,
        file_path=os.path.join(args.output_dir, "pyfolio_daily_nav_and_returns.csv"),
        initial_cash=args.set_cash,
    )


    logger.info("Backtest results saved to %s", args.output_dir)
    logger.info(
        "Returns: mean=%.6f, std=%.6f, sharpe=%.4f",
        returns.mean(),
        returns.std(),
        returns.mean() / returns.std() * (252**0.5) if returns.std() > 0 else 0,
    )


def _register_optimizers(
    config_path: str,
    tuning_params_list: list[dict[str, Any]],
    initial_id: str,
    rebalance_id: str,
    database_instance_id: str = "clickhouse4",
    *,
    prefetch_enabled: bool = True,
    optimizer_backend: str = "mosek-continuous",
    volatility_upper_bound: float = 0.05,
    volatility_penalty_lambda: float = 0.05,
    gurobi_solver_params: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    from quant_pro.infrastructure.calendar.factor_client_adapter import FactorClientCalendar
    from quant_pro.infrastructure.clickhouse.config import build_clickhouse_client_from_config
    from quant_pro.infrastructure.clickhouse.data_fetcher_facade import ClickHouseDataFetcher
    from quant_pro.infrastructure.clickhouse.prefetching_data_fetcher import PrefetchingDataFetcher

    ch_bundle = build_clickhouse_client_from_config(config_path, database_instance_id)
    plain_fetcher = ClickHouseDataFetcher(ch_bundle.client)
    data_fetcher = PrefetchingDataFetcher(plain_fetcher) if prefetch_enabled else plain_fetcher
    return data_fetcher, FactorClientCalendar()


def _load_borrow_slips(slips_path: str | None) -> pd.DataFrame:
    if slips_path and os.path.exists(slips_path):
        ss_df = pd.read_csv(slips_path, low_memory=False)
        if "cre_time" in ss_df.columns:
            ss_df.set_index("cre_time", inplace=True, drop=True)
        ss_df["est_fail_prob"] = 0
        ss_df["est_available_percentage"] = 1
        ss_df["due"] = 1
        return ss_df
    return pd.DataFrame(
        columns=[
            "instrument",
            "available",
            "id",
            "apply_rate",
            "est_fail_prob",
            "est_available_percentage",
        ]
    )


def _run_backtest(
    *,
    weight: pd.DataFrame | list[pd.DataFrame],
    tuning_params_list: list[dict[str, Any]],
    ss_df: pd.DataFrame,
    market_data: Any,
    execution_end_date: str | None = None,
    holding_num: int = 60,
    rolling_num: int = 7,
    persist_path: str = "",
    initial_optimizer_instance_id: str = "",
    rebalance_optimizer_instance_id: str = "",
    initial_position_file_path: str | None = None,
    set_cash: float = 10_000_000.0,
    long_filter_pool_csv: str | None = None,
    short_filter_pool_csv: str | None = None,
    incremental_state_path: str | None = None,
    state_manager: Any | None = None,
    save_daily_state: bool = False,
    daily_state_path: str | None = None,
    prefetch_fetcher: Any | None = None,
    prefetch_calendar: Any | None = None,
    benchmark: str | None = None,
) -> list[Any]:
    np.random.seed(42)

    from quant_pro.adapters.backtrader.analyzers import HedgingAnalyzer
    from quant_pro.adapters.backtrader.brokers import LongShortBackBroker
    from quant_pro.adapters.backtrader.data_feed import init_cerebro_data
    from quant_pro.adapters.backtrader.strategies.longshort import (
        BT_LongShortStockSelectStrategy,
    )

    if incremental_state_path:
        from quant_pro.application.backtest.incremental_state import (
            IncrementalBacktestState,
            resolve_daily_state_path,
        )

        daily_state_path = resolve_daily_state_path(incremental_state_path, daily_state_path)
        if state_manager is None:
            state_manager = IncrementalBacktestState(state_file_path=incremental_state_path)
            if not state_manager.load_from_file():
                raise FileNotFoundError(f"LS incremental state not found: {incremental_state_path}")

    weight_pivots = weight if isinstance(weight, list) else [weight]
    instruments = union_pivot_instruments(weight_pivots)
    start_date, end_date = pivot_date_bounds(weight_pivots)

    if state_manager is not None and hasattr(state_manager, "state"):
        broker_state = state_manager.state.get("broker_state", {})
        historical_positions = broker_state.get("positions", {})
        missing_stocks = set(historical_positions) - set(instruments)
        if missing_stocks:
            logger.warning(
                "LS incremental mode: expanding instruments with %d historical positions",
                len(missing_stocks),
            )
            instruments = list(dict.fromkeys([*instruments, *sorted(missing_stocks)]))

    cerebro = init_cerebro_data(
        instruments=instruments,
        start_date=start_date,
        end_date=pd.Timestamp(execution_end_date) if execution_end_date else end_date,
        market_data=market_data,
        broker_cls=LongShortBackBroker,
        cash=set_cash,
        commission=0.06,
        slippage_perc=0.0003,
        maxcpus=0,
    )

    cerebro.addstrategy(
        BT_LongShortStockSelectStrategy,
        weight=weight,
        holding_num=holding_num,
        rolling_num=rolling_num,
        persist_path=persist_path,
        tuning_params_list=tuning_params_list,
        initial_optimizer_instance_id=initial_optimizer_instance_id,
        rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
        ss_df=ss_df,
        initial_position_file_path=initial_position_file_path,
        enable_daily_stats=True,
        long_filter_pool_csv=long_filter_pool_csv,
        short_filter_pool_csv=short_filter_pool_csv,
        incremental_state_path=incremental_state_path,
        state_manager=state_manager,
        save_daily_state=save_daily_state,
        daily_state_path=daily_state_path,
    )

    cerebro.addanalyzer(HedgingAnalyzer, _name="pyfolio")

    _maybe_prefetch(
        prefetch_fetcher=prefetch_fetcher,
        prefetch_calendar=prefetch_calendar,
        weight_pivots=weight_pivots,
        benchmark=benchmark,
    )

    result: list[Any] = cerebro.run()
    return result


def _ls_benchmark_from_tuning(tuning_params_list: list[dict[str, Any]]) -> str | None:
    for tp in tuning_params_list:
        if isinstance(tp, dict) and "benchmark" in tp:
            return str(tp["benchmark"])
    return None


def _maybe_prefetch(
    *,
    prefetch_fetcher: Any | None,
    prefetch_calendar: Any | None,
    weight_pivots: list[pd.DataFrame],
    benchmark: str | None,
) -> None:
    from quant_pro.infrastructure.clickhouse.prefetching_data_fetcher import (
        PrefetchingDataFetcher,
        build_prefetch_scope,
    )

    if not isinstance(prefetch_fetcher, PrefetchingDataFetcher) or prefetch_calendar is None:
        return
    score_dates = [
        str(pd.Timestamp(idx).strftime("%Y-%m-%d"))
        for pivot in weight_pivots
        if not pivot.empty
        for idx in pivot.index
    ]
    scope = build_prefetch_scope(
        score_dates=score_dates,
        benchmark=benchmark,
        calendar=prefetch_calendar,
    )
    if scope is None:
        return
    try:
        prefetch_fetcher.prefetch(scope)
    except Exception as exc:
        logger.warning("LS prefetch warm-up failed (%s); falling back to per-day queries", exc)


if __name__ == "__main__":
    main()
