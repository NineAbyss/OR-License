
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import backtrader as bt
import pandas as pd

from quant_pro.adapters.backtrader._log_path_helpers import _derive_ei_log_path
from quant_pro.adapters.backtrader.logging import bt_to_log
from quant_pro.adapters.backtrader.strategies.incremental import IncrementalStrategy
from quant_pro.application.backtest.incremental_state import IncrementalBacktestState
from quant_pro.application.optimization.score_inputs import (
    expand_weight_pivots,
    infer_period_num_from_tuning_params,
    union_pivot_instruments,
)
from quant_pro.domain.strategy.enhanced_index_pnl import (
    calculate_long_only_daily_pnl,
    classify_long_only_trade_type,
)
from quant_pro.domain.strategy.limitation import Limitation
from quant_pro.domain.strategy.price_utils import (
    batch_get_none_close,
    get_none_close,
    get_post_factor,
)
from quant_pro.domain.strategy.size_recorder import SizeRecorder
from quant_pro.domain.strategy.todo_recorder import TodoRecorder
from quant_pro.domain.strategy.volume_utils import refine_buy_vol, refine_sell_vol
from quant_pro.infrastructure.clickhouse.queries import LIQUIDITY_FILTER_EVENT_ONLY_QUERY

_CheckpointRecorder = None


def _get_checkpoint_recorder():
    global _CheckpointRecorder
    if _CheckpointRecorder is None:
        try:
            from quant_pro.application.testing.checkpoint_recorder import CheckpointRecorder

            _CheckpointRecorder = CheckpointRecorder
        except ImportError:
            return None
    return _CheckpointRecorder.get()


logger = logging.getLogger(__name__)

progress_logger = logging.getLogger("quant_pro.backtest.progress")


_EI_INCREMENTAL_SCHEMA_VERSION = "enhanced-index-incremental-1"
_LIQUIDITY_FILTER_QUERY_BY_BENCHMARK = {
    "IN932000": LIQUIDITY_FILTER_EVENT_ONLY_QUERY,
    "IN000922": LIQUIDITY_FILTER_EVENT_ONLY_QUERY,
}


def _get_optimizer_service(optimizer_id: str) -> Any:
    from quant_pro.application.services.optimizer_service import get_optimizer

    return get_optimizer(optimizer_id)


class EnhancedIndexStrategy(IncrementalStrategy, bt.Strategy):

    params = (
        ("weight", None),
        ("holding_num", 60),
        ("rolling_num", 7),
        ("persist_path", ""),
        ("tuning_params_list", None),
        ("initial_optimizer_instance_id", ""),
        ("rebalance_optimizer_instance_id", ""),
        ("database_instance_id", ""),
        ("config_path", None),
        ("new_filter", False),
        ("benchmark", None),
        ("initial_position_file_path", None),
        ("is_t0_trading", False),
        ("optimizer_initial", None),
        ("optimizer_rebalance", None),
        ("enable_daily_stats", True),
        ("record_trade_position_log", True),
        ("incremental_state_path", None),
        ("state_manager", None),
        ("save_daily_state", False),
        ("daily_state_path", None),
        ("incremental_next_trade_date", None),
    )

    def __init__(self) -> None:
        super().__init__()

        self._period_num = infer_period_num_from_tuning_params(self.p.tuning_params_list)
        self._weight_periods = self._normalize_weight_tables(self.p.weight, self._period_num)
        self._weight = self._weight_periods[0] if self._weight_periods else pd.DataFrame()
        self._weight_columns = union_pivot_instruments(self._weight_periods)
        self.trade_dates = pd.to_datetime(self._weight.index).tolist()
        self._progress_total = len(self.trade_dates)
        self._progress_seen: set[Any] = set()
        self._progress_starting_value: float | None = None
        self.order_list: list[Any] = []
        self.buy_stocks_pre: list[str] = []
        self.is_need_init_position = True
        self.position_record: list[pd.DataFrame] = []
        self.long_money = 0.0
        self.do_close = False
        self.done_close = False

        self.initial_optimizer = self._resolve_optimizer(
            self.p.optimizer_initial, self.p.initial_optimizer_instance_id
        )
        self.rebalance_optimizer = self._resolve_optimizer(
            self.p.optimizer_rebalance, self.p.rebalance_optimizer_instance_id
        )

        if self.p.tuning_params_list is not None:
            for opt in (self.initial_optimizer, self.rebalance_optimizer):
                if opt is not None and hasattr(opt, "set_tuning_params_list"):
                    opt.set_tuning_params_list(self.p.tuning_params_list)

        self.limitation = Limitation()
        self.sr = SizeRecorder()
        self.tr = TodoRecorder(name="EnhancedIndex_todo", record=True, replay=True, skip=False)
        persist_path = self.p.persist_path or ""
        if persist_path:
            self.tr.set_save_dir(os.path.join(persist_path, "todo_record"))
        self.log_path = _derive_ei_log_path(self.p.persist_path or "")

        self.initial_position_file_path = self.p.initial_position_file_path

        self.enable_daily_stats: bool = bool(self.p.enable_daily_stats)
        self.record_trade_position_log: bool = bool(self.p.record_trade_position_log)
        self.initial_cash: float | None = None
        self.daily_position_stats: list[dict] = []
        self.daily_pnl_stats: list[dict] = []
        self.daily_long_stats: list[dict] = []
        self.daily_stock_summary: list[dict] = []
        self._trade_events: list[dict] = []
        self._position_snapshots: list[dict] = []

        self._prev_total_value: float | None = None
        self._prev_positions: dict[str, dict[str, float]] = {}
        self._daily_trade_accum: dict[str, dict[str, float]] = {}
        self.incremental_init(
            state_manager=self.p.state_manager,
            save_daily_state=self.p.save_daily_state,
            daily_state_path=self.p.daily_state_path,
        )

    def start(self) -> None:
        super().start()
        self.incremental_start()

        if not self.is_incremental or self.state_manager is None:
            return

        strategy_state = self.state_manager.get_strategy_state()
        broker_positions = self.state_manager.get_broker_state().get("positions", {})
        if not strategy_state:
            if broker_positions:
                self.is_need_init_position = False
                self._restore_size_recorder_from_broker_positions(broker_positions)
            return

        saved_version = strategy_state.get("_schema_version")
        if saved_version and saved_version != _EI_INCREMENTAL_SCHEMA_VERSION:
            logger.warning(
                "EI incremental state schema mismatch: saved=%s, current=%s",
                saved_version,
                _EI_INCREMENTAL_SCHEMA_VERSION,
            )

        default_init_position = not self.state_manager.has_positions()
        self.is_need_init_position = strategy_state.get(
            "_is_need_init_position",
            strategy_state.get("init_position", default_init_position),
        )
        self.buy_stocks_pre = list(strategy_state.get("buy_stocks_pre", []))
        self.long_money = float(strategy_state.get("long_money", self.long_money))
        self.do_close = bool(strategy_state.get("do_close", False))
        self.done_close = bool(strategy_state.get("done_close", False))
        self._prev_total_value = strategy_state.get("_prev_total_value")
        self._prev_positions = {
            str(k): dict(v) for k, v in strategy_state.get("_prev_positions", {}).items()
        }
        self._daily_trade_accum = {
            str(k): dict(v) for k, v in strategy_state.get("_daily_trade_accum", {}).items()
        }
        self.position_record = list(strategy_state.get("position_record", []))
        self.daily_position_stats = list(strategy_state.get("daily_position_stats", []))
        self.daily_pnl_stats = list(strategy_state.get("daily_pnl_stats", []))
        self.daily_long_stats = list(strategy_state.get("daily_long_stats", []))
        self.daily_stock_summary = list(strategy_state.get("daily_stock_summary", []))
        self._trade_events = list(strategy_state.get("_trade_events", []))
        self._position_snapshots = list(strategy_state.get("_position_snapshots", []))

        sr_state = self.state_manager.get_sr_state()
        if "size_recorder" in sr_state:
            self.sr.size_recorder = {
                str(k): int(v) for k, v in sr_state.get("size_recorder", {}).items()
            }
        elif broker_positions:
            self._restore_size_recorder_from_broker_positions(broker_positions)

    def _restore_size_recorder_from_broker_positions(
        self,
        broker_positions: dict[str, dict[str, Any]],
    ) -> None:
        self.sr.size_recorder = {
            str(stock): int(position.get("size", 0))
            for stock, position in broker_positions.items()
            if int(position.get("size", 0)) != 0
        }

    def _resolve_optimizer(self, direct_optimizer: Any, optimizer_id: str) -> Any:
        if direct_optimizer is not None:
            return direct_optimizer
        if not isinstance(optimizer_id, str) or not optimizer_id:
            return None
        return _get_optimizer_service(optimizer_id)

    @staticmethod
    def _normalize_weight_table(weight: Any) -> pd.DataFrame:
        if weight is None:
            return pd.DataFrame()
        frame = weight.copy()
        frame.index = pd.to_datetime(frame.index).normalize()
        return frame.sort_index()

    @staticmethod
    def _normalize_weight_tables(weight: Any, period_num: int) -> list[pd.DataFrame]:
        return expand_weight_pivots(weight, period_num)

    def _get_weight_series(self, today: Any, period_idx: int = 0) -> pd.Series:
        try:
            weight_periods = object.__getattribute__(self, "_weight_periods")
        except AttributeError:
            weight_periods = None
        if weight_periods:
            weight = weight_periods[min(period_idx, len(weight_periods) - 1)]
        else:
            try:
                weight = object.__getattribute__(self, "_weight")
            except AttributeError:
                weight = pd.DataFrame()
        if weight is None or weight.empty:
            return pd.Series(dtype=float)
        today_ts = pd.Timestamp(today).normalize()
        if today_ts not in weight.index:
            return pd.Series(dtype=float)
        return weight.loc[today_ts].dropna().sort_values(ascending=False)

    def _build_optimizer_score_payload(
        self,
        today: Any,
        *,
        allowed_instruments: pd.Index | list[str] | set[str] | None = None,
    ) -> pd.DataFrame | list[pd.DataFrame]:
        try:
            period_num = object.__getattribute__(self, "_period_num")
        except AttributeError:
            period_num = 1
        allowed_set = set(allowed_instruments) if allowed_instruments is not None else None
        liquid_list = self.liquidity_filter_2(pd.Timestamp(today).strftime("%Y-%m-%d"))
        frames: list[pd.DataFrame] = []
        for period_idx in range(max(period_num, 1)):
            weight_today = self._get_weight_series(today, period_idx)
            if allowed_set is not None:
                weight_today = weight_today[weight_today.index.isin(allowed_set)]
            weight_today = weight_today[weight_today.index.isin(liquid_list)]
            frame = pd.DataFrame(
                {
                    "datetime": today,
                    "instrument": weight_today.index,
                    "score": weight_today.values,
                }
            )
            frames.append(frame)
        return frames if len(frames) > 1 else frames[0]

    def _to_log(self, dt: datetime, txt: str) -> None:
        if self.log_path:
            bt_to_log(dt, txt, self.log_path)

    def _get_today(self, datas: Any) -> datetime:
        return pd.to_datetime(datas[0].datetime.date(0))

    def _get_next_trade_day(self, datas: Any) -> datetime:
        return pd.to_datetime(datas[0].datetime.date(1))

    def _get_incremental_next_trade_day(self, today: Any) -> pd.Timestamp | None:
        next_trade_date = self.p.incremental_next_trade_date
        if next_trade_date is None:
            return None

        try:
            next_ts = pd.to_datetime(next_trade_date).normalize()
            today_ts = pd.to_datetime(today).normalize()
        except (ValueError, TypeError):
            logger.warning("Invalid EI incremental_next_trade_date: %s", next_trade_date)
            return None

        if next_ts <= today_ts:
            logger.warning(
                "Ignoring EI incremental_next_trade_date=%s because today=%s",
                next_ts,
                today_ts,
            )
            return None
        return next_ts

    def _remove_delist_stocks(
        self, today: Any, next_trade_day: Any, weight_today: pd.Series
    ) -> None:
        from quant_pro.domain.strategy.price_utils import (
            batch_get_none_close,
            get_none_close,
        )

        if not self.sr.size_recorder:
            return

        stocks = list(self.sr.size_recorder.keys())

        try:
            next_closes = batch_get_none_close(next_trade_day, stocks)
        except Exception:
            next_closes = []
            for stock in stocks:
                try:
                    next_closes.append(get_none_close(next_trade_day, stock))
                except Exception:
                    next_closes.append(None)

        delisted_stocks = []
        for stock, next_close in zip(stocks, next_closes, strict=False):
            if pd.isna(next_close) and (stock.startswith("SH") or stock.startswith("SZ")):
                delisted_stocks.append(stock)

        if not delisted_stocks:
            return

        for stock in delisted_stocks:
            if stock in self.sr.size_recorder:
                self.sr.rm_size(stock)
                self._to_log(today, f"股票 {stock} 在 {next_trade_day} 已退市，已从持仓中移除")

        for stock_name in delisted_stocks:
            try:
                data = self.getdatabyname(stock_name)
            except Exception:
                continue
            if data is not None and data in self.broker.positions:
                position = self.broker.positions[data]
                if position.size != 0:
                    self._to_log(
                        today, f"股票 {stock_name} 已退市，强制平仓。仓位: {position.size}"
                    )
                    position.size = 0

        for stock_name in delisted_stocks:
            if stock_name in weight_today.index:
                weight_today.drop(stock_name, inplace=True)
                self._to_log(today, f"已从优化器输入数据中移除退市股票 {stock_name}")


    def _get_positions(self, size_filter=lambda size: True) -> pd.Series:
        positions_data = []
        positions_index = []
        for d, p in self.getpositions().items():
            if size_filter(p.size):
                positions_data.append(p.size * self.getdatabyname(d._name).close[0])
                positions_index.append(d._name)
        return pd.Series(positions_data, index=positions_index)

    def _create_bond_data(self, trading_date: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        bond_data = pd.DataFrame(
            data=[
                [
                    trading_date.strftime("%Y-%m-%d"),
                    "SZ000001",
                    10000,
                    0.1,
                    f"{trading_date.strftime('%Y%m%d')}0000010",
                ],
                [
                    trading_date.strftime("%Y-%m-%d"),
                    "SH600000",
                    10000,
                    0.1,
                    f"{trading_date.strftime('%Y%m%d')}6000000",
                ],
            ],
            columns=["cre_time", "instrument", "available", "apply_rate", "id"],
        )
        bond_data_by_date = bond_data.set_index("cre_time").copy()
        bond_data["id"] = bond_data["id"].astype(int)
        bond_lookup_table = bond_data.set_index("id").drop(columns=["cre_time"]).copy()
        return bond_data_by_date, bond_lookup_table

    def _process_limitation(self, sell_todo, buy_todo, today):
        dont_sell = self.limitation.get_sell_limit(today)
        dont_buy = self.limitation.get_buy_limit(today)

        sell_mask = ~sell_todo["instrument"].isin(dont_sell[dont_sell].index)
        buy_mask = ~buy_todo["instrument"].isin(dont_buy[dont_buy].index)

        dont_sell_todo = sell_todo[~sell_mask].copy()
        dont_buy_todo = buy_todo[~buy_mask].copy()

        filtered_sell_todo = sell_todo[sell_mask].copy()
        filtered_buy_todo = buy_todo[buy_mask].copy()

        return filtered_sell_todo, filtered_buy_todo, dont_sell_todo, dont_buy_todo

    def _all_score_instruments(self) -> list[str]:
        try:
            instruments = object.__getattribute__(self, "_weight_columns")
        except AttributeError:
            try:
                fallback_weight = object.__getattribute__(self, "_weight")
            except AttributeError:
                return []
            instruments = fallback_weight.columns
        return [str(inst) for inst in list(instruments)]

    def _liquidity_filter_benchmark(self) -> str | None:
        explicit = getattr(self.p, "benchmark", None)
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        tuning_params_list = getattr(self.p, "tuning_params_list", None) or []
        for tuning_params in tuning_params_list:
            if isinstance(tuning_params, dict) and tuning_params.get("benchmark"):
                return str(tuning_params["benchmark"]).strip()
        return None

    @staticmethod
    def _liquidity_filter_query_template(benchmark: str | None) -> str:
        if benchmark in _LIQUIDITY_FILTER_QUERY_BY_BENCHMARK:
            return _LIQUIDITY_FILTER_QUERY_BY_BENCHMARK[benchmark]
        raise ValueError(
            "new_filter liquidity_filter_2 supports benchmarks "
            f"{sorted(_LIQUIDITY_FILTER_QUERY_BY_BENCHMARK)}; got {benchmark!r}"
        )

    def _liquidity_filter_config_path(self) -> str:
        explicit = getattr(self.p, "config_path", None)
        if explicit is not None and str(explicit).strip():
            return str(explicit)
        return (
            os.environ.get("QUANT_PRO_DB_CONFIG")
            or os.environ.get("BACKTESTER_CONFIG")
            or "config.yaml"
        )

    def liquidity_filter_2(self, dt: str) -> list[str]:
        if not bool(getattr(self.p, "new_filter", False)):
            return self._all_score_instruments()

        benchmark = self._liquidity_filter_benchmark()
        query_template = self._liquidity_filter_query_template(benchmark)

        from quant_pro.infrastructure.clickhouse.config import (
            ClickHouseConnectionError,
            build_clickhouse_client_from_config,
        )

        try:
            config_path = self._liquidity_filter_config_path()
            database_instance_id = str(self.p.database_instance_id or "clickhouse4")
            bundle = build_clickhouse_client_from_config(config_path, database_instance_id)
            try:
                result = bundle.client.query(query_template.format(dt=dt))
            finally:
                try:
                    bundle.client._disconnect()
                except Exception as disconnect_error:
                    logger.warning("liquidity_filter_2 disconnect failed: %s", disconnect_error)
            instruments = [str(inst) for inst in result["instrument"].tolist()]
            if instruments:
                return instruments
            fallback = self._all_score_instruments()
            logger.warning(
                "liquidity_filter_2 returned empty universe for %s; "
                "event/liquidity data may be missing, returning all %d score instruments",
                dt,
                len(fallback),
            )
            return fallback
        except ClickHouseConnectionError:
            raise
        except Exception as e:
            logger.warning("liquidity_filter_2 failed: %s, returning all instruments", e)
            return self._all_score_instruments()


    def _init_position(self, today: datetime, next_trade_day: datetime, bond: pd.DataFrame) -> None:
        self.long_money = self.broker.get_value()

        todo = None
        if self.initial_position_file_path and os.path.exists(self.initial_position_file_path):
            todo = pd.read_csv(self.initial_position_file_path)
            logger.info("read stfile %s", self.initial_position_file_path)
        else:
            opt_weight = self._build_optimizer_score_payload(today)

            todo = self.initial_optimizer.optimize(
                pred=opt_weight,
                bond=bond,
                total_value=self.long_money,
            )
            if self.initial_position_file_path and todo is not None:
                todo.to_csv(self.initial_position_file_path, index=False)
                logger.info("save stfile to %s", self.initial_position_file_path)

        if todo is None:
            logger.info("start position todo is None")
            return

        value = self.long_money

        buy_todo = todo
        dont_buy = self.limitation.get_buy_limit(today)
        buy_mask = ~buy_todo["instrument"].isin(dont_buy[dont_buy].index)
        dont_buy_todo = buy_todo[~buy_mask].copy()
        buy_todo = buy_todo[buy_mask].copy()

        if not dont_buy_todo.empty:
            self._to_log(
                today,
                f"计划在[{next_trade_day}]买入排除: {dont_buy_todo.instrument.to_list()}, 少买入权重({sum(dont_buy_todo['weight'])})",
            )

        _net_buy_count = 0.0
        for row in buy_todo.iterrows():
            idx = row[1]["instrument"]
            wei = row[1]["weight"]
            if wei <= 0:
                continue
            none_close = (
                (self.getdatabyname(idx).close[0] / get_post_factor(today, idx))
                if self.p.is_t0_trading
                else get_none_close(today, idx)
            )
            target_money = value * wei
            target_vol = target_money / none_close
            ok, real_vol = refine_buy_vol(idx, target_vol)
            real_money = real_vol * none_close
            if ok:
                _bt_price = self.getdatabyname(idx).close[0]
                bt_vol = real_money / _bt_price
                sr_info = {"vol": real_vol}
                order = self.buy(data=self.getdatabyname(idx), size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(
                    order,
                    "buy",
                    data=self.getdatabyname(idx),
                    size=bt_vol,
                    sr=sr_info,
                )
                _sr_size = self.sr.get_size(idx)
                self._to_log(
                    today,
                    f"[多]计划买入: {idx} vol({real_vol}) "
                    f"bt_vol ({bt_vol}) bt_price({_bt_price}) "
                    f"target({target_vol}) close price({none_close}) "
                    f"money({real_money}) ref({order.ref}) sr({_sr_size})",
                )
                _net_buy_count += real_money
            else:
                self._to_log(
                    today,
                    f"[多]计划买入失败: {idx} vol({real_vol}) traget({target_vol})",
                )
        self._to_log(today, f"[多]计划净买入: {_net_buy_count}")
        self.is_need_init_position = False


    def _progress_long_count(self) -> int:
        return sum(1 for _, p in self.getpositions().items() if p.size > 0)

    def _emit_progress(self, today: Any) -> None:
        if today in self._progress_seen:
            return
        self._progress_seen.add(today)
        seen = len(self._progress_seen)

        nav_value = float(self.broker.getvalue())
        if self._progress_starting_value is None:
            start = getattr(self.broker, "startingcash", None)
            self._progress_starting_value = float(start) if start else nav_value
        start_value = self._progress_starting_value
        nav = nav_value / start_value if start_value else 1.0

        today_ts = pd.Timestamp(today)
        date_str = today_ts.strftime("%Y-%m-%d") if not pd.isna(today_ts) else str(today)

        progress_logger.info(
            "回测进度: %s (%d/%d) | 净值 %.4f | 持仓 %d",
            date_str,
            seen,
            self._progress_total,
            nav,
            self._progress_long_count(),
        )


    def next(self) -> None:
        today = self._get_today(self.datas)

        if today not in self.trade_dates:
            self.incremental_next(today)
            return

        self._emit_progress(today)

        if self.enable_daily_stats and self.initial_cash is None:
            self.initial_cash = float(self.broker.getcash())
            self._to_log(today, f"🏦 记录初始现金: {self.initial_cash:,.2f}")

        next_trade_day = None
        explicit_next_trade_day = self._get_incremental_next_trade_day(today)
        try:
            next_trade_day = self._get_next_trade_day(self.datas)
        except Exception:
            next_trade_day = explicit_next_trade_day
            if next_trade_day is None:
                self.do_close = True
        else:
            if explicit_next_trade_day is not None:
                last_trade_date = pd.to_datetime(self.trade_dates[-1]).normalize()
                if pd.to_datetime(today).normalize() >= last_trade_date:
                    next_trade_day = explicit_next_trade_day

        if self.done_close:
            self.incremental_next(today)
            return

        if self.do_close:
            self.done_close = True
            positions = self._get_positions(lambda size: size != 0)
            for s in positions.index:
                sr_info = {"vol": self.sr.get_size(s), "close_all": True}
                order = self.close(data=self.getdatabyname(s), sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(
                    order,
                    "sell",
                    data=self.getdatabyname(s),
                    sr=sr_info,
                )
            long_value = float(self._get_positions(lambda size: size > 0).sum())
            self._emit_daily_stats(today, long_value, is_terminal_close=True)
            self.incremental_next(today)
            return

        bond, bond_table = self._create_bond_data(today)

        if self.is_need_init_position:
            self._init_position(today, next_trade_day, bond)
            self.incremental_next(today)
            return

        self._record_position_snapshot(today)

        positions = self._get_positions(lambda size: size != 0)
        value = positions.sum() + self.broker.cash
        positions = positions / value

        sizes = pd.Series({d._name: p.size for d, p in self.getpositions().items() if p.size != 0})

        position_record = pd.DataFrame(
            {
                "datetime": today,
                "stock": positions.index,
                "size": sizes.values,
                "percent": positions.values,
                "close": [self.getdatabyname(s).close[0] for s in positions.index],
                "none_size": [self.sr.get_size(s) for s in positions.index],
                "none_clse": batch_get_none_close(today, positions.index),
            }
        )
        self.position_record.append(position_record)

        rec = _get_checkpoint_recorder()
        if rec:
            today_str = today.strftime("%Y-%m-%d")
            rec.record(
                today_str,
                "S9_daily_position",
                position_count=len(position_record),
                cash=self.broker.getcash(),
                portfolio_value=self.broker.getvalue(),
                positions=position_record,
            )

        pos_posi = self._get_positions(lambda size: size > 0)
        long_pure_value = pos_posi.sum()
        long_cash = self.broker.cash
        long_value = long_pure_value + long_cash

        self._to_log(
            today,
            f"long_value({long_pure_value}) cash({self.broker.cash}) nav({self.broker.getvalue()})",
        )

        value = long_value
        weight_today = self._get_weight_series(today)

        if today != pd.to_datetime(self._weight.index[-1]):
            self._remove_delist_stocks(today, next_trade_day, weight_today)

        opt_posi, delisted_stocks = self.sr.get_position(today, next_trade_day)


        opt_posi["apply_rate"] = 0.0

        opt_weight = self._build_optimizer_score_payload(
            today,
            allowed_instruments=weight_today.index,
        )

        todo = None
        if self.tr is None:
            todo = self.rebalance_optimizer.optimize(
                pred=opt_weight,
                bond=bond,
                total_value=value,
                position=opt_posi,
                bond_table=bond_table,
            )
        else:
            todo, skip = self.tr.replay(today)
            if todo is None:
                if skip:
                    self._to_log(today, f"无法优化, [{next_trade_day}]无法交易")
                    self.incremental_next(today)
                    return
                todo = self.rebalance_optimizer.optimize(
                    pred=opt_weight,
                    bond=bond,
                    total_value=value,
                    position=opt_posi,
                    bond_table=bond_table,
                )
                self.tr.record(todo, today)

        if todo is None:
            self._to_log(today, f"无法优化, [{next_trade_day}]无法交易")
            self.incremental_next(today)
            return

        todo["update"] = todo["weight"] - todo["yester_weight"]
        todo = todo[todo["update"] != 0]

        sell_todo = todo[todo["update"] < -(10 ** (-9))].copy()
        buy_todo = todo[todo["update"] > 10 ** (-9)].copy()

        sell_todo["update_money"] = sell_todo["update"] * value
        buy_todo["update_money"] = buy_todo["update"] * value

        sell_todo, buy_todo, dont_sell_todo, dont_buy_todo = self._process_limitation(
            sell_todo, buy_todo, today
        )

        if not dont_sell_todo.empty:
            self._to_log(
                today,
                f"计划在[{next_trade_day}]卖出排除: {dont_sell_todo.instrument.to_list()}, 少卖出金额({sum(dont_sell_todo['update_money'])})",
            )
        if not dont_buy_todo.empty:
            self._to_log(
                today,
                f"计划在[{next_trade_day}]买入排除: {dont_buy_todo.instrument.to_list()}, 少买入金额({sum(dont_buy_todo['update_money'])})",
            )

        self._to_log(
            today,
            f"sell_todo: {sell_todo.shape[0]}. buy_todo: {buy_todo.shape[0]} ",
        )

        _net_sell_count = 0.0
        for row in sell_todo.iterrows():
            idx = row[1]["instrument"]
            target_money = abs(row[1]["update_money"])
            none_close = (
                (self.getdatabyname(idx).close[0] / get_post_factor(today, idx))
                if self.p.is_t0_trading
                else get_none_close(today, idx)
            )
            target_vol = target_money / none_close

            is_close, ok, real_vol = refine_sell_vol(idx, target_vol, self.sr.get_size(idx))
            real_money = real_vol * none_close
            _bt_price = self.getdatabyname(idx).close[0]

            if (
                is_close
                or (row[1]["weight"] < 10 ** (-9) and row[1]["yester_weight"] != 0)
                or (real_vol == self.sr.get_size(idx))
            ):
                sr_info = {"vol": self.sr.get_size(idx), "close_all": True}
                order = self.close(data=self.getdatabyname(idx), sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(
                    order,
                    "sell",
                    data=self.getdatabyname(idx),
                    sr=sr_info,
                )
                _sr_size = self.sr.get_size(idx)
                self._to_log(
                    today,
                    f"[多]计划close: {idx} vol({real_vol}) "
                    f"bt_price({_bt_price}) close price({none_close}) "
                    f"money({real_money}) ref({order.ref}) sr({_sr_size})",
                )
                _net_sell_count += real_money
                continue
            if ok:
                bt_vol = real_money / _bt_price
                sr_info = {"vol": real_vol}
                order = self.sell(data=self.getdatabyname(idx), size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(
                    order,
                    "sell",
                    data=self.getdatabyname(idx),
                    size=bt_vol,
                    sr=sr_info,
                )
                _sr_size = self.sr.get_size(idx)
                self._to_log(
                    today,
                    f"[多]计划卖出: {idx} vol({real_vol}) "
                    f"target({target_vol}) bt_price({_bt_price}) "
                    f"bt_vol ({bt_vol}) close price({none_close}) "
                    f"money({real_money}) ref({order.ref}) sr({_sr_size})",
                )
                _net_sell_count += real_money
            else:
                self._to_log(
                    today,
                    f"[多]计划卖出失败: {idx} vol({real_vol}) traget({target_vol})",
                )
        self._to_log(today, f"[多]计划净卖出: {_net_sell_count}")

        _net_buy_count = 0.0
        for row in buy_todo.iterrows():
            idx = row[1]["instrument"]
            target_money = row[1]["update_money"]
            none_close = (
                (self.getdatabyname(idx).close[0] / get_post_factor(today, idx))
                if self.p.is_t0_trading
                else get_none_close(today, idx)
            )
            target_vol = target_money / none_close

            ok, real_vol = refine_buy_vol(idx, target_vol)
            real_money = real_vol * none_close
            if ok:
                _bt_price = self.getdatabyname(idx).close[0]
                bt_vol = real_money / _bt_price
                sr_info = {"vol": real_vol}
                order = self.buy(data=self.getdatabyname(idx), size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(
                    order,
                    "buy",
                    data=self.getdatabyname(idx),
                    size=bt_vol,
                    sr=sr_info,
                )
                _sr_size = self.sr.get_size(idx)
                self._to_log(
                    today,
                    f"[多]计划买入: {idx} vol({real_vol}) "
                    f"bt_vol ({bt_vol}) bt_price({_bt_price}) "
                    f"target({target_vol}) close price({none_close}) "
                    f"money({real_money}) ref({order.ref}) sr({_sr_size})",
                )
                _net_buy_count += real_money
            else:
                self._to_log(
                    today,
                    f"[多]计划买入失败: {idx} vol({real_vol}) traget({target_vol})",
                )
        self._to_log(today, f"[多]计划净买入: {_net_buy_count}")

        self._emit_daily_stats(today, long_value)

        rec = _get_checkpoint_recorder()
        if rec:
            today_str = today.strftime("%Y-%m-%d")
            rec.record(
                today_str,
                "S10_eod_nav",
                nav=self.broker.getvalue(),
                cash=self.broker.getcash(),
            )

        self.incremental_next(today)


    def notify_order(self, order: Any) -> None:
        today = self._get_today(self.datas)
        status = self._get_order_status(order)

        if status == "Completed":
            if "sr" not in order.info:
                logger.warning("%s has no sr in order info", order.data._name)
                return

            sr_info = order.info["sr"]
            vol = sr_info["vol"]

            inst = order.data._name
            if order.isbuy():
                self._to_log(
                    today,
                    f"Long: BUY {inst}, Money({order.executed.value:.2f}) "
                    f"order.executed.size({order.executed.size}) "
                    f"order.executed.price({order.executed.price}) "
                    f"real vol {vol} none_close {sr_info.get('none_close', '')} "
                    f"ref({order.ref}) ",
                )
                self.sr.ad_size(order.data._name, vol)
            else:
                self._to_log(
                    today,
                    f"Long: SELL {inst}, Money({order.executed.value:.2f}) "
                    f"order.executed.size({order.executed.size}) "
                    f"order.executed.price({order.executed.price}) "
                    f"real vol {vol} ref({order.ref})",
                )
                self.sr.rm_size(order.data._name, vol)

            exec_size_abs = abs(float(order.executed.size))
            exec_price = float(order.executed.price)
            exec_cash_abs = exec_size_abs * exec_price

            if self.record_trade_position_log:
                self._trade_events.append(
                    {
                        "date": pd.Timestamp(today).strftime("%Y-%m-%d"),
                        "instrument": inst,
                        "side": "BUY" if order.isbuy() else "SELL",
                        "real_vol": vol,
                        "bt_size": order.executed.size,
                        "exec_price": order.executed.price,
                        "exec_value": exec_cash_abs,
                        "commission": order.executed.comm,
                        "ref": order.ref,
                    }
                )

            exec_comm = float(order.executed.comm) if order.executed.comm is not None else 0.0
            accum = self._daily_trade_accum.setdefault(
                inst,
                {
                    "buy_size": 0.0,
                    "buy_value": 0.0,
                    "sell_size": 0.0,
                    "sell_value": 0.0,
                    "commission": 0.0,
                },
            )
            if order.isbuy():
                accum["buy_size"] += exec_size_abs
                accum["buy_value"] += exec_cash_abs
            else:
                accum["sell_size"] += exec_size_abs
                accum["sell_value"] += exec_cash_abs
            accum["commission"] += exec_comm

            rec = _get_checkpoint_recorder()
            if rec:
                today_str = today.strftime("%Y-%m-%d")
                side = "BUY" if order.isbuy() else "SELL"
                rec.record(
                    today_str,
                    "S7_order_notify",
                    instrument=order.data._name,
                    side=side,
                    real_vol=sr_info.get("vol", 0),
                    bt_size=order.executed.size,
                    exec_price=order.executed.price,
                    commission=order.executed.comm,
                )

        elif status in {"Canceled", "Margin", "Partial"}:
            self._to_log(today, f"{order.data._name} 交易失败 Status: {status}")
            if status == "Partial":
                self._to_log(today, "special case >> Partial")
                self._to_log(today, f"order ref : {order.ref}")
                self._to_log(today, f"stock : {order.data._name}")
                self._to_log(
                    today,
                    f"price({order.executed.price}) size({order.executed.size}) "
                    f"value({order.executed.value})",
                )
        elif status in {"Rejected", "Expired"}:
            self._to_log(today, f"{order.data._name} 交易失败 Status: {status}")

    @staticmethod
    def _get_order_status(order: Any) -> str:
        status_map = {
            order.Completed: "Completed",
            order.Canceled: "Canceled",
            order.Margin: "Margin",
            order.Partial: "Partial",
            order.Created: "Created",
            order.Submitted: "Submitted",
            order.Accepted: "Accepted",
            order.Rejected: "Rejected",
            order.Expired: "Expired",
        }
        return status_map.get(order.status, "Unknown")


    def _emit_daily_stats(
        self,
        today: Any,
        long_value: float,
        *,
        is_terminal_close: bool = False,
    ) -> None:
        if not self.enable_daily_stats:
            return

        dt_str = pd.Timestamp(today).strftime("%Y-%m-%d")

        current_nav = float(self.broker.getvalue())

        if self._prev_total_value is not None:
            prev_nav = self._prev_total_value
        elif self.initial_cash is not None:
            prev_nav = float(self.initial_cash)
        else:
            prev_nav = current_nav

        broker_nav_delta = current_nav - prev_nav
        daily_return = broker_nav_delta / prev_nav if prev_nav != 0 else 0.0

        long_rows: list[dict] = []
        total_long_value = 0.0
        stock_pnl = 0.0

        data_by_name: dict[str, Any] = {}
        for data in self.datas:
            if getattr(data, "_name", "") == "exchange_calendar":
                continue
            data_by_name[data._name] = data

        processed_names: set[str] = set()

        for name, data in data_by_name.items():
            try:
                pos = self.broker.getposition(data)
            except Exception:
                continue
            curr_size = float(pos.size)
            close_px = float(data.close[0])
            prev_info = self._prev_positions.get(name, {})
            prev_size = float(prev_info.get("size", 0.0))
            prev_close = prev_info.get("close")
            prev_close_f = float(prev_close) if prev_close is not None else None
            trade = self._daily_trade_accum.get(name, {})
            buy_value = float(trade.get("buy_value", 0.0))
            sell_value = float(trade.get("sell_value", 0.0))
            buy_size = float(trade.get("buy_size", 0.0))
            sell_size = float(trade.get("sell_size", 0.0))

            pos_pnl = calculate_long_only_daily_pnl(
                prev_size=prev_size,
                prev_close=prev_close_f,
                current_size=curr_size,
                current_close=close_px,
                buy_value=buy_value,
                sell_value=sell_value,
            )
            stock_pnl += pos_pnl
            processed_names.add(name)

            if curr_size > 0:
                mv = curr_size * close_px
                total_long_value += mv
                trade_type = classify_long_only_trade_type(
                    prev_size=prev_size,
                    current_size=curr_size,
                    net_buy_size=buy_size,
                    net_sell_size=sell_size,
                )
                long_rows.append(
                    {
                        "date": dt_str,
                        "instrument": name,
                        "size": curr_size,
                        "close": close_px,
                        "market_value": mv,
                        "trade_type": trade_type,
                    }
                )

        for name, prev_info in self._prev_positions.items():
            if name in processed_names:
                continue
            prev_size = float(prev_info.get("size", 0.0))
            prev_close = prev_info.get("close")
            prev_close_f = float(prev_close) if prev_close is not None else None
            trade = self._daily_trade_accum.get(name, {})
            buy_value = float(trade.get("buy_value", 0.0))
            sell_value = float(trade.get("sell_value", 0.0))
            pos_pnl = calculate_long_only_daily_pnl(
                prev_size=prev_size,
                prev_close=prev_close_f,
                current_size=0.0,
                current_close=prev_close_f if prev_close_f is not None else 0.0,
                buy_value=buy_value,
                sell_value=sell_value,
            )
            stock_pnl += pos_pnl

        self._to_log(
            today,
            f"长头明细: {len(long_rows)} positions, total_long_value={total_long_value:,.2f}",
        )
        self.daily_long_stats.extend(long_rows)
        self.daily_position_stats.append(
            {
                "date": dt_str,
                "long_count": len(long_rows),
                "long_total_value": total_long_value,
            }
        )

        daily_commission = sum(
            float(t.get("commission", 0.0) or 0.0) for t in self._daily_trade_accum.values()
        )
        if daily_commission == 0.0 and self.record_trade_position_log:
            for ev in self._trade_events:
                if ev.get("date") == dt_str:
                    daily_commission += float(ev.get("commission", 0.0) or 0.0)

        commission_pnl = -daily_commission
        theoretical_pnl = stock_pnl + commission_pnl
        residual = broker_nav_delta - theoretical_pnl

        cumulative_pnl = (
            current_nav - float(self.initial_cash) if self.initial_cash is not None else 0.0
        )

        self._to_log(
            today,
            f"今日盈亏合计: gross_pnl={cumulative_pnl:,.2f} nav={current_nav:,.2f}",
        )

        self._to_log(
            today,
            (
                f"资产核对: prev_nav={prev_nav:,.2f} nav={current_nav:,.2f} "
                f"delta={broker_nav_delta:,.2f} stock_pnl={stock_pnl:,.2f} "
                f"commission_pnl={commission_pnl:,.2f} theoretical={theoretical_pnl:,.2f} "
                f"residual={residual:,.4f}"
            ),
        )

        tolerance = max(1.0, 0.001 * abs(prev_nav)) if prev_nav else 1.0
        if abs(residual) > tolerance:
            self._to_log(
                today,
                (
                    f"⚠️ NAV reconciliation drift: residual={residual:,.4f} "
                    f"(theoretical={theoretical_pnl:,.2f} vs "
                    f"broker_delta={broker_nav_delta:,.2f}, tolerance={tolerance:,.4f})"
                ),
            )

        self.daily_pnl_stats.append(
            {
                "date": dt_str,
                "prev_nav": prev_nav,
                "nav": current_nav,
                "broker_nav_delta": broker_nav_delta,
                "daily_return": daily_return,
                "stock_pnl": stock_pnl,
                "commission": daily_commission,
                "commission_pnl": commission_pnl,
                "theoretical_pnl": theoretical_pnl,
                "residual": residual,
                "cumulative_pnl": cumulative_pnl,
                "gross_pnl": cumulative_pnl,
                "is_terminal_close": is_terminal_close,
            }
        )
        self.daily_stock_summary.append(
            {
                "date": dt_str,
                "n_long": len(long_rows),
                "total_long_value": total_long_value,
            }
        )

        self._prev_total_value = current_nav
        new_prev_positions: dict[str, dict[str, float]] = {}
        for name, data in data_by_name.items():
            try:
                pos = self.broker.getposition(data)
            except Exception:
                continue
            if pos.size != 0:
                close_px = float(data.close[0])
                new_prev_positions[name] = {
                    "size": float(pos.size),
                    "close": close_px,
                    "mv": float(pos.size) * close_px,
                }
        self._prev_positions = new_prev_positions
        self._daily_trade_accum = {}

    def _save_daily_state(self, current_date: Any) -> None:
        assert self.daily_state_path is not None

        try:
            date_str = pd.to_datetime(current_date).strftime("%Y%m%d")
            date_hyphen = pd.to_datetime(current_date).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            logger.debug("Date parse fallback for current_date=%s", current_date)
            date_str = str(current_date).replace("-", "")[:8]
            date_hyphen = str(current_date)[:10]

        state_file = os.path.join(self.daily_state_path, f"state_{date_str}.pkl")
        sm = IncrementalBacktestState(state_file_path=state_file)

        if hasattr(self, "broker"):
            broker = self.broker
            positions: dict[str, dict[str, Any]] = {}
            if hasattr(broker, "positions"):
                for data, pos in broker.positions.items():
                    if pos.size != 0 and hasattr(data, "_name"):
                        positions[data._name] = {
                            "size": pos.size,
                            "price": pos.price,
                            "adjbase": getattr(pos, "adjbase", None),
                        }
            sm.save_broker_state(
                cash=broker.cash,
                value=broker.getvalue() if hasattr(broker, "getvalue") else 0.0,
                positions=positions,
                fundshares=getattr(broker, "_fundshares", 1.0),
                fundval=getattr(broker, "_fundval", 100.0),
            )

        ei_extra: dict[str, Any] = {
            "_schema_version": _EI_INCREMENTAL_SCHEMA_VERSION,
            "_strategy_name": "EnhancedIndexStrategy",
            "_is_need_init_position": self.is_need_init_position,
            "buy_stocks_pre": list(self.buy_stocks_pre),
            "long_money": self.long_money,
            "do_close": self.do_close,
            "done_close": self.done_close,
            "_prev_total_value": self._prev_total_value,
            "_prev_positions": self._prev_positions,
            "_daily_trade_accum": self._daily_trade_accum,
            "position_record": list(self.position_record),
            "daily_position_stats": list(self.daily_position_stats),
            "daily_pnl_stats": list(self.daily_pnl_stats),
            "daily_long_stats": list(self.daily_long_stats),
            "daily_stock_summary": list(self.daily_stock_summary),
            "_trade_events": list(self._trade_events),
            "_position_snapshots": list(self._position_snapshots),
        }
        sm.save_strategy_state(
            prev_dt=date_hyphen,
            init_position=self.is_need_init_position,
            initial_cash=getattr(self, "initial_cash", None),
            prev_total_value=getattr(self, "_prev_total_value", None),
            prev_positions=getattr(self, "_prev_positions", None),
            extra=ei_extra,
        )

        sm.state["sr_state"] = {"size_recorder": dict(self.sr.size_recorder)}
        sm.state["last_date"] = date_hyphen
        os.makedirs(self.daily_state_path, exist_ok=True)
        sm.save_to_file()
        logger.info("Daily state saved (EI): %s", state_file)

    def _record_position_snapshot(self, dt: Any) -> None:
        if not getattr(self, "record_trade_position_log", False):
            return
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        for data in self.datas:
            if getattr(data, "_name", "") == "exchange_calendar":
                continue
            try:
                position = self.broker.getposition(data)
            except Exception:
                continue
            if position.size != 0:
                inst = data._name
                side = "long"
                self._position_snapshots.append(
                    {
                        "date": date_str,
                        "instrument": inst,
                        "position_side": side,
                        "size": abs(position.size),
                        "price": float(data.close[0]),
                        "market_value": abs(position.size) * float(data.close[0]),
                    }
                )

    def _compute_position_changes(self) -> pd.DataFrame:
        if not self._position_snapshots:
            return pd.DataFrame()

        snap_df = pd.DataFrame(self._position_snapshots)
        dates = sorted(snap_df["date"].unique())
        if len(dates) < 2:
            return pd.DataFrame()

        all_changes: list[dict] = []
        key_cols = ["instrument", "position_side"]

        for i in range(1, len(dates)):
            prev_date = dates[i - 1]
            curr_date = dates[i]
            prev_snap = snap_df[snap_df["date"] == prev_date]
            curr_snap = snap_df[snap_df["date"] == curr_date]

            prev_idx = prev_snap.set_index(key_cols)[["size"]].rename(columns={"size": "prev_size"})
            curr_idx = curr_snap.set_index(key_cols)[["size"]].rename(
                columns={"size": "current_size"}
            )
            merged = prev_idx.join(curr_idx, how="outer").fillna(0)
            merged["delta_size"] = merged["current_size"] - merged["prev_size"]
            merged["date"] = curr_date

            for (inst, pos_side), row in merged.iterrows():
                prev_sz = row["prev_size"]
                curr_sz = row["current_size"]
                if prev_sz == 0 and curr_sz != 0:
                    ctype = "open"
                elif prev_sz != 0 and curr_sz == 0:
                    ctype = "close"
                elif row["delta_size"] != 0:
                    ctype = "change"
                else:
                    ctype = "hold"
                all_changes.append(
                    {
                        "date": curr_date,
                        "instrument": inst,
                        "position_side": pos_side,
                        "prev_size": prev_sz,
                        "current_size": curr_sz,
                        "delta_size": row["delta_size"],
                        "change_type": ctype,
                    }
                )

        return pd.DataFrame(all_changes) if all_changes else pd.DataFrame()

    def _save_lightweight_reports(self) -> None:
        persist = getattr(self.p, "persist_path", "") or ""
        if not persist:
            return
        try:
            os.makedirs(persist, exist_ok=True)
        except Exception:
            return

        if self._trade_events:
            pd.DataFrame(self._trade_events).to_csv(
                os.path.join(persist, "trade_events.csv"), index=False
            )

        if self._position_snapshots:
            pd.DataFrame(self._position_snapshots).to_csv(
                os.path.join(persist, "position_snapshot_log.csv"), index=False
            )
            changes = self._compute_position_changes()
            if not changes.empty:
                changes.to_csv(os.path.join(persist, "position_change_log.csv"), index=False)

    def stop(self) -> None:
        final_value = float(self.broker.getvalue())
        start_value = self._progress_starting_value
        if start_value is None:
            start = getattr(self.broker, "startingcash", None)
            start_value = float(start) if start else final_value
        final_nav = final_value / start_value if start_value else 1.0
        progress_logger.info(
            "回测完成: 共 %d 个调仓日 | 最终净值 %.4f | 输出 %s",
            len(self._progress_seen),
            final_nav,
            self.p.persist_path or "(无)",
        )

        if self.position_record:
            position = pd.concat(self.position_record).set_index("datetime").sort_index()
            persist_path = self.p.persist_path
            if persist_path:
                position.to_csv(os.path.join(persist_path, "position_record.csv"))

        if getattr(self, "record_trade_position_log", False):
            self._save_lightweight_reports()

        persist_path = self.p.persist_path
        if persist_path and self.enable_daily_stats:
            try:
                os.makedirs(persist_path, exist_ok=True)
                if self.daily_position_stats:
                    pd.DataFrame(self.daily_position_stats).to_csv(
                        os.path.join(persist_path, "daily_position_stats.csv"), index=False
                    )
                if self.daily_pnl_stats:
                    pd.DataFrame(self.daily_pnl_stats).to_csv(
                        os.path.join(persist_path, "daily_pnl_stats.csv"), index=False
                    )
                if self.daily_long_stats:
                    pd.DataFrame(self.daily_long_stats).to_csv(
                        os.path.join(persist_path, "daily_long_stats.csv"), index=False
                    )
                if self.daily_stock_summary:
                    pd.DataFrame(self.daily_stock_summary).to_csv(
                        os.path.join(persist_path, "daily_stock_summary.csv"), index=False
                    )
            except Exception as exc:
                logger.warning("EI daily stats CSV persist failed: %s", exc)


class BT_EnhancedIndexStockSelectStrategy(EnhancedIndexStrategy):
    pass


__all__ = [
    "EnhancedIndexStrategy",
    "BT_EnhancedIndexStockSelectStrategy",
]
