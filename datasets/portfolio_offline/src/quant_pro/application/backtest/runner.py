
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Protocol

import pandas as pd

from quant_pro.application.backtest.naming import build_run_label
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
from quant_pro.domain.ports.price_data import PriceDataPort
from quant_pro.domain.utils.validation import validate_index_launch_date

logger = logging.getLogger(__name__)


_FILTER_NONE_VALUES = {"", "none", "null", "empty"}


def _infer_next_trade_date(weight: pd.DataFrame, end_time: str | datetime | None) -> str | None:
    if end_time is None or "datetime" not in weight.columns:
        return None

    end_ts = pd.to_datetime(end_time)
    future_dates = weight.loc[weight["datetime"] > end_ts, "datetime"].dropna()
    if future_dates.empty:
        return None
    return str(pd.Timestamp(future_dates.min()).strftime("%Y-%m-%d"))




class CerebroFactory(Protocol):

    def __call__(
        self,
        instruments: Sequence[str],
        start_date: Any,
        end_date: Any,
        market_data: Any,
        **kwargs: Any,
    ) -> Any: ...


class MarketDataLoader(Protocol):

    def __call__(
        self,
        limit_start: str | datetime | None = None,
        limit_end: str | datetime | None = None,
        factors: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> Any: ...




def _get_benchmark_from_config(
    tuning_params_list: list[dict[str, Any]],
) -> str | None:
    for params in tuning_params_list:
        if "benchmark" in params:
            return str(params["benchmark"])
    logger.warning("配置文件中未找到 benchmark 参数")
    return None


def _resolve_filter(
    filter_spec: str | Callable[..., Any] | None,
) -> Callable[..., Any] | None:
    if filter_spec is None:
        return None

    if callable(filter_spec):
        return filter_spec

    if not isinstance(filter_spec, str):
        raise TypeError("filter must be a callable, a shortcut string, or None")

    normalized_filter_spec = filter_spec.strip().lower()
    if normalized_filter_spec in _FILTER_NONE_VALUES:
        return None

    _filters: dict[str, Callable[..., Any]] = {
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

    if normalized_filter_spec not in _filters:
        raise ValueError(
            f"Unknown filter shortcut '{filter_spec}'. Supported: {list(_filters.keys())}"
        )
    return _filters[normalized_filter_spec]


def _setup_output_dir(output_root_dir: str, model_name: str) -> tuple[str, str]:
    output_dir = os.path.join(output_root_dir, "out", model_name)
    os.makedirs(output_dir, exist_ok=True)
    initial_position_file_path = os.path.join(output_dir, "st.csv")
    return output_dir, initial_position_file_path


def _set_custom_price_data(
    vwapopen: str | None,
    vwapclose: str | None,
) -> None:
    from data_process import datas, load_factors

    if vwapopen is not None:
        _ = load_factors([vwapopen])
        datas.day.open = datas.day[vwapopen]
    if vwapclose is not None:
        _ = load_factors([vwapclose])
        datas.day.close = datas.day[vwapclose]




class BacktestRunner:

    def __init__(
        self,
        cerebro_factory: CerebroFactory,
        market_data_loader: MarketDataLoader,
        price_data_port: PriceDataPort | None = None,
    ) -> None:
        self._cerebro_factory = cerebro_factory
        self._market_data_loader = market_data_loader
        self._price_data_port = price_data_port


    def run_rolling(
        self,
        weight: pd.DataFrame | list[pd.DataFrame],
        tuning_params_list: list[dict[str, Any]],
        *,
        holding_num: int = 60,
        rolling_num: int = 7,
        persist_path: str = "runtime/log",
        initial_optimizer_instance_id: str = "EnhancedIndexInitialOptimizer1",
        rebalance_optimizer_instance_id: str = "EnhancedIndexRebalanceOptimizer1",
        database_instance_id: str = "clickhouse3",
        config_path: str | None = None,
        initial_position_file_path: str | None = None,
        set_cash: float = 10_000_000.0,
        t0: bool = False,
        incremental_state_path: str | None = None,
        state_manager: Any | None = None,
        save_daily_state: bool = False,
        daily_state_path: str | None = None,
        incremental_next_trade_date: str | datetime | None = None,
        new_filter: bool = False,
        benchmark: str | None = None,
        strategy_cls: type | None = None,
        analyzer_cls: type | None = None,
        cerebro_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if strategy_cls is None:
            from quant_pro.adapters.backtrader.strategies.enhanced_index import (
                BT_EnhancedIndexStockSelectStrategy,
            )

            strategy_cls = BT_EnhancedIndexStockSelectStrategy
        if analyzer_cls is None:
            from quant_pro.adapters.backtrader.analyzers import HedgingAnalyzer

            analyzer_cls = HedgingAnalyzer

        if incremental_state_path:
            from quant_pro.application.backtest.incremental_state import (
                IncrementalBacktestState,
                resolve_daily_state_path,
            )

            daily_state_path = resolve_daily_state_path(incremental_state_path, daily_state_path)
            if state_manager is None:
                state_manager = IncrementalBacktestState(state_file_path=incremental_state_path)
                if not state_manager.load_from_file():
                    raise FileNotFoundError(
                        f"EI incremental state not found: {incremental_state_path}"
                    )

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

        market_data = self._market_data_loader(
            limit_start=start_date,
            limit_end=end_date,
        )

        extra = cerebro_kwargs or {}
        cerebro = self._cerebro_factory(
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
            market_data=market_data,
            **extra,
        )
        strategy_benchmark = benchmark
        if strategy_benchmark is None and new_filter:
            strategy_benchmark = _get_benchmark_from_config(tuning_params_list)

        cerebro.addstrategy(
            strategy_cls,
            weight=weight,
            holding_num=holding_num,
            rolling_num=rolling_num,
            persist_path=persist_path,
            tuning_params_list=tuning_params_list,
            initial_optimizer_instance_id=initial_optimizer_instance_id,
            rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
            database_instance_id=database_instance_id,
            config_path=config_path,
            benchmark=strategy_benchmark,
            initial_position_file_path=initial_position_file_path,
            is_t0_trading=t0,
            incremental_state_path=incremental_state_path,
            state_manager=state_manager,
            save_daily_state=save_daily_state,
            daily_state_path=daily_state_path,
            incremental_next_trade_date=incremental_next_trade_date,
            new_filter=new_filter,
        )
        cerebro.addanalyzer(analyzer_cls, _name="pyfolio")
        result = cerebro.run()
        return result


    def run(
        self,
        weight_path: str,
        output_root_dir: str,
        tuning_params_list: list[dict[str, Any]],
        *,
        initial_optimizer_instance_id: str = "EnhancedIndexInitialOptimizer",
        rebalance_optimizer_instance_id: str = "EnhancedIndexRebalanceOptimizer",
        database_instance_id: str = "clickhouse3",
        config_path: str | None = None,
        holding_num: int = 60,
        rolling_num: int = 7,
        vwapopen: str | None = None,
        vwapclose: str | None = None,
        set_cash: float = 10_000_000.0,
        t0: bool = False,
        filter: str | Callable[..., Any] | None = None,
        start_time: str | datetime | None = None,
        end_time: str | datetime | None = None,
        incremental_state_path: str | None = None,
        state_manager: Any | None = None,
        save_daily_state: bool = False,
        daily_state_path: str | None = None,
        incremental_next_trade_date: str | datetime | None = None,
        new_filter: bool = False,
        cerebro_kwargs: dict[str, Any] | None = None,
    ) -> None:
        from data_process import load_factors

        from quant_pro.adapters.backtrader.data_feed import (
            ENHANCED_INDEX_FACTORS,
        )

        _ = load_factors(
            list(ENHANCED_INDEX_FACTORS),
            limit_start=start_time,
            limit_end=end_time,
        )

        if self._price_data_port is not None:
            if vwapopen is not None:
                self._price_data_port.set_custom_open(vwapopen)
            if vwapclose is not None:
                self._price_data_port.set_custom_close(vwapclose)
        else:
            _set_custom_price_data(vwapopen, vwapclose)

        model_name = build_run_label(weight_path, vwapopen, vwapclose, suffix="new_barra_test")
        output_dir, initial_position_file_path = _setup_output_dir(output_root_dir, model_name)
        apply_score_path_auto_default(tuning_params_list, weight_path)
        apply_score_period_auto_metadata(tuning_params_list, weight_path)

        period_num = infer_period_num_from_tuning_params(tuning_params_list)
        score_frames = load_score_frames(weight_path, period_num=period_num)
        raw_weight_pivots = score_frames_to_pivots(score_frames)
        if (
            save_daily_state or incremental_state_path or state_manager is not None
        ) and incremental_next_trade_date is None:
            incremental_next_trade_date = infer_next_trade_date_from_pivots(
                raw_weight_pivots,
                str(end_time) if end_time is not None else None,
            )

        weight_pivots = score_frames_to_pivots(
            score_frames,
            start_time=start_time,
            end_time=end_time,
        )

        benchmark = _get_benchmark_from_config(tuning_params_list)
        first_weight = weight_pivots[0] if weight_pivots else pd.DataFrame()
        if benchmark and not first_weight.empty:
            backtest_start_date = pd.Timestamp(first_weight.index.min()).strftime("%Y-%m-%d")
            logger.info("实际回测开始日期: %s", backtest_start_date)
            validate_index_launch_date(backtest_start_date, benchmark)

        filter_fn = _resolve_filter(filter)
        if filter_fn is not None:
            market_data = self._market_data_loader(
                limit_start=start_time,
                limit_end=end_time,
            )
            mask = filter_fn(market_data.day)
            weight_pivots = [weight_pv.where(mask) for weight_pv in weight_pivots]
        if weight_pivots:
            weight_pivots[0].to_csv(os.path.join(output_dir, "filter_weight.csv"))
            if len(weight_pivots) > 1:
                for idx, weight_pv in enumerate(weight_pivots):
                    weight_pv.to_csv(os.path.join(output_dir, f"filter_weight_p{idx}.csv"))

        result = self.run_rolling(
            weight=weight_pivots if len(weight_pivots) > 1 else weight_pivots[0],
            tuning_params_list=tuning_params_list,
            holding_num=holding_num,
            rolling_num=rolling_num,
            persist_path=output_dir,
            initial_optimizer_instance_id=initial_optimizer_instance_id,
            rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
            database_instance_id=database_instance_id,
            config_path=config_path,
            initial_position_file_path=initial_position_file_path,
            set_cash=set_cash,
            t0=t0,
            incremental_state_path=incremental_state_path,
            state_manager=state_manager,
            save_daily_state=save_daily_state,
            daily_state_path=daily_state_path,
            incremental_next_trade_date=incremental_next_trade_date,
            benchmark=benchmark,
            new_filter=new_filter,
            cerebro_kwargs=cerebro_kwargs,
        )

        pyfolio = result[0].analyzers.pyfolio
        returns, positions, transactions, gross_lev = pyfolio.get_pf_items()

        returns.to_csv(os.path.join(output_dir, "returns.csv"))
        transactions.to_csv(os.path.join(output_dir, "transactions.csv"))
        positions.to_csv(os.path.join(output_dir, "positions.csv"))

        logger.info("Backtest results of %s saved to %s", model_name, output_dir)
