
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_pro.application.backtest.naming import build_run_label
from quant_pro.application.optimization.score_inputs import (
    apply_score_path_auto_default,
    apply_score_period_auto_metadata,
    infer_period_num_from_tuning_params,
    load_score_frames,
    pivot_date_bounds,
    score_frames_to_pivots,
    union_pivot_instruments,
)
from quant_pro.domain.ports.price_data import PriceDataPort

logger = logging.getLogger(__name__)

_LONGSHORT_MARKET_FACTORS: list[str] = [
    "close",
    "open",
    "high",
    "low",
    "volume",
    "total_turnover",
]




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


def save_feather_with_overwrite(data: pd.DataFrame, file_path: str) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)
    data.to_feather(file_path)


def save_daily_nav_and_returns(
    returns: pd.Series,
    gross_lev: pd.Series,
    file_path: str,
    *,
    initial_cash: float,
) -> None:

    returns_series = pd.Series(returns).astype(float).rename("daily_return")
    leverage_series = pd.Series(gross_lev).astype(float).rename("leverage")
    nav = (1.0 + returns_series.fillna(0.0)).cumprod() * float(initial_cash)
    nav_df = pd.concat(
        [
            nav.rename("nav"),
            returns_series,
            leverage_series,
        ],
        axis=1,
    ).reset_index()
    nav_df.rename(columns={nav_df.columns[0]: "date"}, inplace=True)
    nav_df["date"] = pd.to_datetime(nav_df["date"]).dt.strftime("%Y-%m-%d")
    nav_df.to_csv(file_path, index=False)






def _normalize_analysis_date(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    return str(pd.Timestamp(value).strftime("%Y-%m-%d"))


def _coerce_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)




def _list_relative_artifacts(base_dir: Path) -> list[str]:
    if not base_dir.exists():
        return []
    return sorted(
        path.relative_to(base_dir).as_posix() for path in base_dir.rglob("*") if path.is_file()
    )






class LongShortRunner:

    def __init__(
        self,
        cerebro_factory: Callable[..., Any],
        market_data_loader: Callable[..., Any],
        price_data_port: PriceDataPort | None = None,
    ) -> None:
        self._cerebro_factory = cerebro_factory
        self._market_data_loader = market_data_loader
        self._price_data_port = price_data_port


    def run_rolling(
        self,
        weight: pd.DataFrame | list[pd.DataFrame],
        tuning_params_list: list[dict[str, Any]],
        ss_df: pd.DataFrame,
        *,
        holding_num: int = 60,
        rolling_num: int = 7,
        persist_path: str = "runtime/log",
        initial_optimizer_instance_id: str = "LongShortInitialOptimizer1",
        rebalance_optimizer_instance_id: str = "LongShortRebalanceOptimizer1",
        initial_position_file_path: str | None = None,
        set_cash: float = 10_000_000.0,
        enable_daily_stats: bool = True,
        record_trade_position_log: bool = True,
        incremental_state_path: str | None = None,
        state_manager: Any | None = None,
        save_daily_state: bool = False,
        daily_state_path: str | None = None,
        strategy_cls: type | None = None,
        analyzer_cls: type | None = None,
        cerebro_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        np.random.seed(42)

        if strategy_cls is None:
            from quant_pro.adapters.backtrader.strategies.longshort import (
                BT_LongShortStockSelectStrategy,
            )

            strategy_cls = BT_LongShortStockSelectStrategy
        if analyzer_cls is None:
            from quant_pro.adapters.backtrader.analyzers import HedgingAnalyzer

            analyzer_cls = HedgingAnalyzer
        if cerebro_kwargs is None:
            from quant_pro.adapters.backtrader.brokers import (
                LongShortBackBroker,
            )

            extra: dict[str, Any] = {
                "broker_cls": LongShortBackBroker,
                "commission": 0.06,
                "maxcpus": 0,
            }
        else:
            extra = dict(cerebro_kwargs)
            if "broker_cls" not in extra:
                from quant_pro.adapters.backtrader.brokers import (
                    LongShortBackBroker,
                )

                extra["broker_cls"] = LongShortBackBroker
            extra.setdefault("commission", 0.06)
            extra.setdefault("maxcpus", 0)

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
                        f"LS incremental state not found: {incremental_state_path}"
                    )

        weight_pivots = weight if isinstance(weight, list) else [weight]
        instruments = union_pivot_instruments(weight_pivots)
        start_date, end_date = pivot_date_bounds(weight_pivots)

        market_data = self._market_data_loader(
            limit_start=start_date,
            limit_end=end_date,
            factors=_LONGSHORT_MARKET_FACTORS,
        )

        cerebro = self._cerebro_factory(
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
            market_data=market_data,
            **extra,
        )

        if state_manager is not None or save_daily_state:
            if state_manager is not None and hasattr(state_manager, "state"):
                broker_state = state_manager.state.get("broker_state", {})
                historical_positions = broker_state.get("positions", {})
                historical_stocks = set(historical_positions.keys())
                current_stocks = set(instruments)
                missing_stocks = historical_stocks - current_stocks
                if missing_stocks:
                    logger.warning(
                        "Incremental mode: %d historical positions not in "
                        "current weight (suspended?), expanding instruments",
                        len(missing_stocks),
                    )
                    instruments = list(current_stocks | missing_stocks)
                    market_data = self._market_data_loader(
                        limit_start=start_date,
                        limit_end=end_date,
                        factors=_LONGSHORT_MARKET_FACTORS,
                    )
                    cerebro = self._cerebro_factory(
                        instruments=instruments,
                        start_date=start_date,
                        end_date=end_date,
                        market_data=market_data,
                        **extra,
                    )

            cerebro.addstrategy(
                strategy_cls,
                weight=weight,
                holding_num=holding_num,
                rolling_num=rolling_num,
                persist_path=persist_path,
                tuning_params_list=tuning_params_list,
                initial_optimizer_instance_id=initial_optimizer_instance_id,
                rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
                ss_df=ss_df,
                initial_position_file_path=initial_position_file_path,
                enable_daily_stats=enable_daily_stats,
                record_trade_position_log=record_trade_position_log,
                incremental_state_path=incremental_state_path,
                state_manager=state_manager,
                save_daily_state=save_daily_state,
                daily_state_path=daily_state_path,
            )
        else:
            cerebro.addstrategy(
                strategy_cls,
                weight=weight,
                holding_num=holding_num,
                rolling_num=rolling_num,
                persist_path=persist_path,
                tuning_params_list=tuning_params_list,
                initial_optimizer_instance_id=initial_optimizer_instance_id,
                rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
                ss_df=ss_df,
                initial_position_file_path=initial_position_file_path,
                enable_daily_stats=enable_daily_stats,
                record_trade_position_log=record_trade_position_log,
                incremental_state_path=incremental_state_path,
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
        initial_optimizer_instance_id: str = "LongShortInitialOptimizer1",
        rebalance_optimizer_instance_id: str = "LongShortRebalanceOptimizer1",
        holding_num: int = 60,
        rolling_num: int = 7,
        vwapopen: str | None = None,
        vwapclose: str | None = None,
        set_cash: float = 10_000_000.0,
        start_time: str | datetime | None = None,
        end_time: str | datetime | None = None,
        slips_path: str = str(
            Path(__file__).resolve().parents[4]
            / "tests/test_data/score_and_comp_slips/merged_bonds_240301_251225.csv"
        ),
        enable_daily_stats: bool = True,
        record_trade_position_log: bool = True,
        incremental_state_path: str | None = None,
        state_manager: Any | None = None,
        save_daily_state: bool = False,
        daily_state_path: str | None = None,
        cerebro_kwargs: dict[str, Any] | None = None,
        emit_attribution: bool = True,
        attribution_output_dir: str | None = None,
        attribution_database_id: str = "clickhouse4",
        attribution_config_file_path: str | None = None,
        barra_config_file: str | None = None,
    ) -> Any:
        if self._price_data_port is not None:
            if vwapopen is not None:
                self._price_data_port.set_custom_open(vwapopen)
            if vwapclose is not None:
                self._price_data_port.set_custom_close(vwapclose)
        else:
            _set_custom_price_data(vwapopen, vwapclose)

        model_name = build_run_label(weight_path, vwapopen, vwapclose)
        output_dir, initial_position_file_path = _setup_output_dir(output_root_dir, model_name)
        apply_score_path_auto_default(tuning_params_list, weight_path)
        apply_score_period_auto_metadata(tuning_params_list, weight_path)

        period_num = infer_period_num_from_tuning_params(tuning_params_list)
        score_frames = load_score_frames(weight_path, period_num=period_num)
        weight_pivots = score_frames_to_pivots(
            score_frames,
            start_time=start_time,
            end_time=end_time,
        )

        ss_df = pd.read_csv(slips_path, low_memory=False)
        ss_df.set_index("cre_time", inplace=True, drop=True)
        ss_df["est_fail_prob"] = 0
        ss_df["est_available_percentage"] = 1
        ss_df["due"] = 1

        result = self.run_rolling(
            weight=weight_pivots if len(weight_pivots) > 1 else weight_pivots[0],
            tuning_params_list=tuning_params_list,
            ss_df=ss_df,
            holding_num=holding_num,
            rolling_num=rolling_num,
            persist_path=output_dir,
            initial_optimizer_instance_id=initial_optimizer_instance_id,
            rebalance_optimizer_instance_id=rebalance_optimizer_instance_id,
            initial_position_file_path=initial_position_file_path,
            set_cash=set_cash,
            enable_daily_stats=enable_daily_stats,
            record_trade_position_log=record_trade_position_log,
            incremental_state_path=incremental_state_path,
            state_manager=state_manager,
            save_daily_state=save_daily_state,
            daily_state_path=daily_state_path,
            cerebro_kwargs=cerebro_kwargs,
        )

        pyfolio = result[0].analyzers.pyfolio
        returns, positions, transactions, gross_lev = pyfolio.get_pf_items()

        save_feather_with_overwrite(
            returns.to_frame(),
            os.path.join(output_dir, "returns.feather"),
        )
        save_feather_with_overwrite(
            transactions,
            os.path.join(output_dir, "transactions.feather"),
        )
        save_feather_with_overwrite(
            positions,
            os.path.join(output_dir, "positions.feather"),
        )
        returns.to_csv(os.path.join(output_dir, "returns.csv"))
        transactions.to_csv(os.path.join(output_dir, "transactions.csv"))
        transactions.to_csv(os.path.join(output_dir, "txn.csv"))
        positions.to_csv(os.path.join(output_dir, "positions.csv"))
        pyfolio_nav_path = os.path.join(output_dir, "pyfolio_daily_nav_and_returns.csv")
        save_daily_nav_and_returns(
            returns=returns,
            gross_lev=gross_lev,
            file_path=pyfolio_nav_path,
            initial_cash=set_cash,
        )



        logger.info("Backtest results of %s saved to %s", model_name, output_dir)
        return result
