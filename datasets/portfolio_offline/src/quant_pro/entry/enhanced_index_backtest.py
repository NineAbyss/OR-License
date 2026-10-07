
from __future__ import annotations

import argparse
import logging
import os
import re
from typing import Any

import pandas as pd
import yaml

from quant_pro.application.optimization.score_inputs import (
    apply_score_path_auto_default,
    apply_score_period_auto_metadata,
    infer_next_trade_date_from_pivots,
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

_ATTRIBUTION_FACTOR_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")

_ATTRIBUTION_MODE_CHOICES: tuple[str, ...] = (
    "brinson_industry",
    "brinson_component",
    "brinson_factor",
    "barra",
    "all",
)

_BOOLEAN_TRUE_VALUES = {"true", "1", "yes", "y"}
_BOOLEAN_FALSE_VALUES = {"false", "0", "no", "n"}

_FILTER_NONE_VALUES = {"", "none", "null", "empty"}
_FILTER_CHOICES: tuple[str, ...] = (
    "event",
    "event_and_1000",
    "event_and_500",
    "1000",
    "500",
)

_NEW_FILTER_SUPPORTED_BENCHMARKS = {"IN932000", "IN000922"}


def _validate_attribution_factor_name(value: str) -> str:
    if not _ATTRIBUTION_FACTOR_NAME_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"--attribution_factor_name must match ^[a-zA-Z][a-zA-Z0-9_]{{0,63}}$ (got {value!r})"
        )
    return value


def _parse_bool_arg(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _BOOLEAN_TRUE_VALUES:
        return True
    if normalized in _BOOLEAN_FALSE_VALUES:
        return False
    raise argparse.ArgumentTypeError(
        f"expected one of true/false, 1/0, yes/no, y/n (case-insensitive); got {value!r}"
    )


def _normalize_filter_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in _FILTER_NONE_VALUES:
        return None
    if normalized not in _FILTER_CHOICES:
        raise argparse.ArgumentTypeError(
            f"unknown --filter value {value!r}; supported values: "
            f"{', '.join(_FILTER_CHOICES)}; pass none/null/empty for no filter"
        )
    return normalized


def _validate_new_filter_benchmark(benchmark: str | None) -> None:
    if benchmark in _NEW_FILTER_SUPPORTED_BENCHMARKS:
        return
    raise ValueError(
        "--new_filter True requires tuning_params benchmark to be one of "
        f"{sorted(_NEW_FILTER_SUPPORTED_BENCHMARKS)}; got {benchmark!r}"
    )


try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _check_index_launch_date(current_date: str, benchmark: str) -> None:
    INDEX_LAUNCH_DATES = {
        "IN932000": "2023-08-31",
        "IN000300": "2008-01-02",
        "IN000905": "2008-01-02",
        "IN000852": "2014-10-31",
        "IN866006": "2015-12-31",
        "IN000922": "2008-05-30",
    }
    INDEX_NAMES = {
        "IN932000": "中证2000",
        "IN000300": "沪深300",
        "IN000905": "中证500",
        "IN000852": "中证1000",
        "IN866006": "微盘股指数",
        "IN000922": "红利指数",
    }
    if benchmark not in INDEX_LAUNCH_DATES:
        logger.warning("未知的指数代码 %s，跳过上市日期检查", benchmark)
        return
    launch_date = INDEX_LAUNCH_DATES[benchmark]
    index_name = INDEX_NAMES.get(benchmark, benchmark)
    if current_date < launch_date:
        raise ValueError(
            f"回测日期 {current_date} 早于 {index_name}({benchmark}) 的上市日期 {launch_date}"
        )
    logger.info("指数日期检查通过: %s(%s) 上市日期 %s", index_name, benchmark, launch_date)


def _get_benchmark_from_config(tuning_params_list: list[dict[str, Any]]) -> str | None:
    for tp in tuning_params_list:
        if "benchmark" in tp:
            return str(tp["benchmark"])
    return None


def _infer_next_trade_date(weight: pd.DataFrame, end_time: str | None) -> str | None:
    if end_time is None or "datetime" not in weight.columns:
        return None

    end_ts = pd.to_datetime(end_time)
    future_dates = weight.loc[weight["datetime"] > end_ts, "datetime"].dropna()
    if future_dates.empty:
        return None
    return str(pd.Timestamp(future_dates.min()).strftime("%Y-%m-%d"))


def _default_daily_state_path(
    save_daily_state: bool,
    daily_state_path: str | None,
    output_dir: str | None,
) -> str | None:
    if save_daily_state and daily_state_path is None and output_dir:
        return os.path.join(output_dir, "incremental")
    return daily_state_path


def main() -> None:
    parser = argparse.ArgumentParser(description="EnhancedIndex standalone backtest")
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
        help="backtest config (env: QUANT_PRO_DB_CONFIG)",
    )
    parser.add_argument("--initial_optimizer_id", default="NewEnhancedIndexInitialOptimizer1")
    parser.add_argument("--rebalance_optimizer_id", default="NewEnhancedIndexRebalanceOptimizer1")
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
    parser.add_argument("--t0", action="store_true", help="T0 trading mode")
    parser.add_argument("--start_time", default=None)
    parser.add_argument("--end_time", default=None)
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
        "--filter",
        default=None,
        type=_normalize_filter_name,
        help=(
            "Entrance-layer score filter: event, event_and_1000, event_and_500, "
            "1000, 500. Default/unset and none/null/empty mean no entrance filter."
        ),
    )
    parser.add_argument(
        "--new_filter",
        default=False,
        type=_parse_bool_arg,
        help=(
            "Explicit boolean. True enables the strategy-level event/liquidity "
            "filter; False disables it. Accepted values: true/false, 1/0, "
            "yes/no, y/n. Default: False."
        ),
    )
    parser.add_argument(
        "--incremental_state_path",
        default=None,
        help="Path to a saved EI incremental state pickle for resume mode.",
    )
    parser.add_argument(
        "--save_daily_state",
        action="store_true",
        help="Save EI incremental state/order pickles at the end of each bar.",
    )
    parser.add_argument(
        "--daily_state_path",
        default=None,
        help="Directory for EI incremental state/order pickles.",
    )
    parser.add_argument(
        "--incremental_next_trade_date",
        default=None,
        help=(
            "Next trading date after --end_time for EI prepare mode. "
            "If omitted, inferred from the unfiltered weight file when possible."
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
    logger.info("EnhancedIndex standalone backtest starting")

    with open(args.tuning_params) as f:
        tuning_params_list = yaml.safe_load(f)
    if isinstance(tuning_params_list, dict):
        _ordinals = {"first", "second", "third", "fourth", "fifth", "sixth"}
        if _ordinals & set(tuning_params_list.keys()):
            tuning_params_list = list(tuning_params_list.values())
        else:
            tuning_params_list = [tuning_params_list]
    apply_score_path_auto_default(tuning_params_list, args.weight_path)
    apply_score_period_auto_metadata(tuning_params_list, args.weight_path)

    prefetch_enabled = not args.no_prefetch_cache
    prefetch_fetcher, prefetch_calendar = _register_optimizers(
        args.config_path,
        tuning_params_list,
        args.initial_optimizer_id,
        args.rebalance_optimizer_id,
        args.database_instance_id,
        prefetch_enabled=prefetch_enabled,
    )

    from quant_pro.adapters.backtrader.data_feed import (
        ENHANCED_INDEX_FACTORS,
        lazy_load_market_data,
    )

    market_data = lazy_load_market_data(
        limit_start=args.start_time,
        limit_end=args.end_time,
        factors=ENHANCED_INDEX_FACTORS,
    )

    from quant_pro.application.backtest.runner import _set_custom_price_data

    _set_custom_price_data(args.vwapopen, args.vwapclose)

    period_num = infer_period_num_from_tuning_params(tuning_params_list)
    score_frames = load_score_frames(args.weight_path, period_num=period_num)
    raw_weight_pivots = score_frames_to_pivots(score_frames)
    incremental_next_trade_date = args.incremental_next_trade_date
    if (
        args.save_daily_state or args.incremental_state_path
    ) and incremental_next_trade_date is None:
        incremental_next_trade_date = infer_next_trade_date_from_pivots(
            raw_weight_pivots,
            args.end_time,
        )

    weight_pivots = score_frames_to_pivots(
        score_frames,
        start_time=args.start_time,
        end_time=args.end_time,
    )

    benchmark = _get_benchmark_from_config(tuning_params_list)
    if args.new_filter:
        _validate_new_filter_benchmark(benchmark)
    first_weight = weight_pivots[0] if weight_pivots else pd.DataFrame()
    if benchmark and not first_weight.empty:
        backtest_start_date = pd.Timestamp(first_weight.index.min()).strftime("%Y-%m-%d")
        _check_index_launch_date(backtest_start_date, benchmark)

    if args.filter is not None:
        weight_pivots = [
            _apply_filter(weight_pv, args.filter, market_data) for weight_pv in weight_pivots
        ]

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
                f"EI incremental state not found: {args.incremental_state_path}"
            )

    daily_state_path = _default_daily_state_path(
        args.save_daily_state, daily_state_path, args.output_dir
    )

    result = _run_backtest(
        weight=weight_pivots if len(weight_pivots) > 1 else weight_pivots[0],
        tuning_params_list=tuning_params_list,
        market_data=market_data,
        holding_num=args.holding_num,
        rolling_num=args.rolling_num,
        persist_path=args.output_dir,
        initial_optimizer_instance_id=args.initial_optimizer_id,
        rebalance_optimizer_instance_id=args.rebalance_optimizer_id,
        initial_position_file_path=initial_position_file_path,
        set_cash=args.set_cash,
        t0=args.t0,
        incremental_state_path=args.incremental_state_path,
        state_manager=state_manager,
        save_daily_state=args.save_daily_state,
        daily_state_path=daily_state_path,
        incremental_next_trade_date=incremental_next_trade_date,
        config_path=args.config_path,
        database_instance_id=args.database_instance_id,
        benchmark=benchmark,
        new_filter=args.new_filter,
        prefetch_fetcher=prefetch_fetcher if prefetch_enabled else None,
        prefetch_calendar=prefetch_calendar,
    )

    pyfolio = result[0].analyzers.pyfolio
    returns, positions, transactions, gross_lev = pyfolio.get_pf_items()

    returns.to_csv(os.path.join(args.output_dir, "returns.csv"))
    transactions.to_csv(os.path.join(args.output_dir, "transactions.csv"))
    positions.to_csv(os.path.join(args.output_dir, "positions.csv"))

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
) -> tuple[Any, Any]:
    from quant_pro.infrastructure.calendar.factor_client_adapter import FactorClientCalendar
    from quant_pro.infrastructure.clickhouse.config import build_clickhouse_client_from_config
    from quant_pro.infrastructure.clickhouse.data_fetcher_facade import ClickHouseDataFetcher
    from quant_pro.infrastructure.clickhouse.prefetching_data_fetcher import PrefetchingDataFetcher

    ch_bundle = build_clickhouse_client_from_config(config_path, database_instance_id)
    plain_fetcher = ClickHouseDataFetcher(ch_bundle.client)
    data_fetcher = PrefetchingDataFetcher(plain_fetcher) if prefetch_enabled else plain_fetcher
    return data_fetcher, FactorClientCalendar()


def _apply_filter(weight_pv: pd.DataFrame, filter_name: str, market_data: Any) -> pd.DataFrame:
    filter_map = {
        "1000": lambda x: (
            (x["rank_vol"] > 0.6)
            | (x["rank_turnover"] > 0.6)
            | (x["rank_buyvol"] > 0.6)
            | (x["rank_bid_ask_spread_all"] > 0.6)
        ),
        "500": lambda x: (
            (x["rank_vol"] > 0.5) | (x["rank_turnover"] > 0.5) | (x["rank_buyvol"] > 0.5)
        ),
        "event": lambda x: x["is_event_accepted_v2"] == 1,
        "event_and_500": lambda x: (
            (x["is_event_accepted_v2"] == 1)
            & ((x["rank_vol"] > 0.5) | (x["rank_turnover"] > 0.5) | (x["rank_buyvol"] > 0.5))
        ),
        "event_and_1000": lambda x: (
            (x["is_event_accepted_v2"] == 1)
            & (
                (x["rank_vol"] > 0.6)
                | (x["rank_turnover"] > 0.6)
                | (x["rank_buyvol"] > 0.6)
                | (x["rank_bid_ask_spread_all"] > 0.6)
            )
        ),
    }

    if filter_name in filter_map:
        mask = filter_map[filter_name](market_data.day)
        return weight_pv.where(mask)
    else:
        raise ValueError(f"Unknown filter: {filter_name}. Available: {list(filter_map.keys())}")


def _run_backtest(
    *,
    weight: pd.DataFrame | list[pd.DataFrame],
    tuning_params_list: list[dict[str, Any]],
    market_data: Any,
    holding_num: int = 60,
    rolling_num: int = 7,
    persist_path: str = "",
    initial_optimizer_instance_id: str = "",
    rebalance_optimizer_instance_id: str = "",
    initial_position_file_path: str | None = None,
    set_cash: float = 10_000_000.0,
    t0: bool = False,
    incremental_state_path: str | None = None,
    state_manager: Any | None = None,
    save_daily_state: bool = False,
    daily_state_path: str | None = None,
    incremental_next_trade_date: str | None = None,
    config_path: str | None = None,
    database_instance_id: str | None = None,
    benchmark: str | None = None,
    new_filter: bool = False,
    prefetch_fetcher: Any | None = None,
    prefetch_calendar: Any | None = None,
) -> list[Any]:
    from quant_pro.adapters.backtrader.analyzers import HedgingAnalyzer
    from quant_pro.adapters.backtrader.brokers import EnhancedIndexBackBroker
    from quant_pro.adapters.backtrader.data_feed import init_cerebro_data
    from quant_pro.adapters.backtrader.strategies.enhanced_index import (
        BT_EnhancedIndexStockSelectStrategy,
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
                raise FileNotFoundError(f"EI incremental state not found: {incremental_state_path}")

    weight_pivots = weight if isinstance(weight, list) else [weight]
    instruments = union_pivot_instruments(weight_pivots)
    start_date, end_date = pivot_date_bounds(weight_pivots)

    if state_manager is not None and hasattr(state_manager, "state"):
        broker_state = state_manager.state.get("broker_state", {})
        historical_positions = broker_state.get("positions", {})
        missing_stocks = set(historical_positions) - set(instruments)
        if missing_stocks:
            logger.warning(
                "EI incremental mode: expanding instruments with %d historical positions",
                len(missing_stocks),
            )
            instruments = list(dict.fromkeys([*instruments, *sorted(missing_stocks)]))

    cerebro = init_cerebro_data(
        instruments=instruments,
        start_date=start_date,
        end_date=end_date,
        market_data=market_data,
        broker_cls=EnhancedIndexBackBroker,
        cash=set_cash,
        commission=0.045,
        slippage_perc=0.0003,
        configure_futures=True,
    )

    cerebro.addstrategy(
        BT_EnhancedIndexStockSelectStrategy,
        weight=weight,
        holding_num=holding_num,
        rolling_num=rolling_num,
        persist_path=persist_path,
        tuning_params_list=tuning_params_list,
        initial_optimizer_instance_id=initial_optimizer_instance_id,
        rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
        database_instance_id=database_instance_id or "",
        config_path=config_path,
        benchmark=benchmark,
        initial_position_file_path=initial_position_file_path,
        is_t0_trading=t0,
        incremental_state_path=incremental_state_path,
        state_manager=state_manager,
        save_daily_state=save_daily_state,
        daily_state_path=daily_state_path,
        incremental_next_trade_date=incremental_next_trade_date,
        new_filter=new_filter,
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
        logger.warning("EI prefetch warm-up failed (%s); falling back to per-day queries", exc)


if __name__ == "__main__":
    main()
