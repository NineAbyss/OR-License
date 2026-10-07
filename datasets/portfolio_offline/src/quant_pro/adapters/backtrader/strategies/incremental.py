
from __future__ import annotations

import collections
import logging
import os
import pickle
from typing import Any

from quant_pro.application.backtest.incremental_state import (
    IncrementalBacktestState,
)

logger = logging.getLogger(__name__)




def restore_broker_state(
    broker: Any,
    datas_dict: dict[str, Any],
    state_manager: IncrementalBacktestState,
) -> bool:
    broker_state = state_manager.get_broker_state()
    if not broker_state or "cash" not in broker_state:
        return False

    broker.cash = broker_state["cash"]

    if "fundshares" in broker_state:
        broker._fundshares = broker_state["fundshares"]
    else:
        broker._fundshares = broker.cash / broker._fundval if broker._fundval > 0 else 1.0

    if "fundval" in broker_state:
        broker._fundval = broker_state["fundval"]
    else:
        broker._fundval = 100.0

    positions = broker_state.get("positions", {})
    for stock_code, pos_data in positions.items():
        if stock_code not in datas_dict:
            logger.warning("Position restore skipped — data not found: %s", stock_code)
            continue

        data = datas_dict[stock_code]
        position = broker.positions[data]
        position.size = pos_data["size"]
        position.price = pos_data["price"]
        position.adjbase = pos_data.get("adjbase")

        if hasattr(data, "datetime") and len(data) > 0:
            position.datetime = data.datetime
        else:
            import datetime as dt_module

            class _MockDatetime:

                @staticmethod
                def date() -> Any:
                    return dt_module.date.today()

            position.datetime = _MockDatetime()

    pending_orders = broker_state.get("pending_orders", [])
    if pending_orders:
        import backtrader as bt

        if not hasattr(broker, "pending"):
            broker.pending = collections.deque()

        for order_data in pending_orders:
            data_name = order_data.get("data_name")
            if data_name not in datas_dict:
                continue

            data = datas_dict[data_name]
            size = order_data["size"]

            if size > 0:
                order = bt.BuyOrder(
                    owner=None,
                    data=data,
                    size=size,
                    price=order_data.get("price"),
                    exectype=order_data.get("exectype"),
                    valid=order_data.get("valid"),
                )
            else:
                order = bt.SellOrder(
                    owner=None,
                    data=data,
                    size=abs(size),
                    price=order_data.get("price"),
                    exectype=order_data.get("exectype"),
                    valid=order_data.get("valid"),
                )

            order.status = order_data.get("status", order.status)
            order.created = order_data.get("created", order.created)
            order.info = order_data.get("info", order.info)
            order.ref = order_data.get("ref", order.ref)
            order.transmit = order_data.get("transmit", True)

            broker.pending.append(order)
            logger.info("Restored pending order: %s size=%s", data_name, size)

    logger.info(
        "Broker state restored: cash=%.2f, positions=%d, pending=%d",
        broker_state["cash"],
        len(positions),
        len(pending_orders),
    )
    return True


def restore_strategy_state(
    strategy: Any,
    state_manager: IncrementalBacktestState,
) -> bool:
    strategy_state = state_manager.get_strategy_state()
    if not strategy_state:
        return False

    prev_dt = strategy_state.get("prev_dt")
    if prev_dt is not None:
        try:
            import pandas as pd

            strategy.prev_dt = pd.to_datetime(prev_dt)
        except (ValueError, TypeError):
            logger.debug("prev_dt parse fallback for %s", prev_dt)
            strategy.prev_dt = prev_dt

    strategy.max_lever_rate = strategy_state.get("max_lever_rate", 0.0)
    strategy.closed_daily_interest = strategy_state.get("closed_daily_interest", 0.0)
    strategy.loss_total = strategy_state.get("loss_total", 0)
    strategy.gain_total = strategy_state.get("gain_total", 0)

    _restore_if_exists(strategy, "prev_positions", strategy_state, default={})
    _restore_if_exists(strategy, "prev_total_value", strategy_state)
    _restore_if_exists(strategy, "initial_cash", strategy_state)
    _restore_if_exists(strategy, "prev_real_value", strategy_state)
    _restore_if_exists(strategy, "decision_scores", strategy_state, default={})
    _restore_if_exists(strategy, "daily_trades_history", strategy_state, default={})

    _restore_if_exists(strategy, "real_trades_today", strategy_state, default={})
    _restore_if_exists(strategy, "real_positions_today", strategy_state, default={})

    if hasattr(strategy, "daily_trades"):
        strategy.daily_trades = {}
    if hasattr(strategy, "daily_trade_summary"):
        strategy.daily_trade_summary = {}

    has_positions = state_manager.has_positions()
    strategy.init_position = not has_positions
    logger.info(
        "Strategy state restored: prev_dt=%s, init_position=%s",
        prev_dt,
        strategy.init_position,
    )

    return True


def restore_sr_state(
    sr: Any,
    state_manager: IncrementalBacktestState,
) -> bool:
    sr_state = state_manager.get_sr_state()
    if not sr_state:
        return False

    sr.size = _normalize_dict_keys(sr_state.get("size", {}))
    sr.money = _normalize_dict_keys(sr_state.get("money", {}))
    sr.apply_rate = _normalize_dict_keys(sr_state.get("apply_rate", {}))
    sr.hold_days = _normalize_dict_keys(sr_state.get("hold_days", {}))
    sr.open_price = _normalize_dict_keys(sr_state.get("open_price", {}))
    sr.exec_size = _normalize_dict_keys(sr_state.get("exec_size", {}))
    sr.partial_order = {}

    instrument_id_set = sr_state.get("instrument_id_set", {})
    sr.instrument_id_set = {k: set(v) for k, v in instrument_id_set.items()}

    logger.info(
        "SR state restored: %d positions, %d instrument_id mappings",
        len(sr.size),
        len(sr.instrument_id_set),
    )
    return True




def _restore_if_exists(
    obj: Any,
    attr: str,
    state: dict[str, Any],
    default: Any = None,
) -> None:
    if hasattr(obj, attr):
        setattr(obj, attr, state.get(attr, default))


def _normalize_dict_keys(d: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in d.items():
        k = str(key) if not isinstance(key, str) else key
        result[k] = value
    return result




class IncrementalStrategy:

    state_manager: IncrementalBacktestState | None
    is_incremental: bool
    save_daily_state: bool
    daily_state_path: str | None
    daily_orders: list[dict[str, Any]]

    def incremental_init(
        self,
        state_manager: IncrementalBacktestState | None = None,
        save_daily_state: bool = False,
        daily_state_path: str | None = None,
    ) -> None:
        self.state_manager = state_manager
        self.is_incremental = state_manager is not None
        self.save_daily_state = save_daily_state
        self.daily_state_path = daily_state_path
        self.daily_orders = []

    def incremental_start(self) -> None:
        if self.is_incremental and self.state_manager is not None:
            logger.info("Incremental mode: restoring state and resubmitting orders")
            self._restore_state()
            self._resubmit_previous_orders()

    def record_order_if_preparing(
        self,
        order: Any,
        order_type: str,
        **kwargs: Any,
    ) -> None:
        if not getattr(self, "save_daily_state", False) or order is None:
            return
        self._record_order(order, order_type, **kwargs)

    def incremental_next(self, current_date: Any) -> None:
        if self.save_daily_state and self.daily_state_path:
            self._save_daily_state(current_date)
            self._save_daily_orders(current_date)


    def _record_order(self, order: Any, order_type: str, **kwargs: Any) -> None:
        data = kwargs.get("data")
        data_name = data._name if data is not None and hasattr(data, "_name") else None

        sr_info = kwargs.get("sr")
        safe_sr: dict[str, Any] = {}
        if sr_info and isinstance(sr_info, dict):
            for key, value in sr_info.items():
                if isinstance(value, (int, float, str, bool, type(None))):
                    safe_sr[key] = value
                else:
                    safe_sr[key] = str(value)

        order_info: dict[str, Any] = {
            "order_type": order_type,
            "data_name": data_name,
            "size": kwargs.get("size"),
            "sr": safe_sr,
            "exectype": kwargs.get("exectype"),
            "price": kwargs.get("price"),
        }
        self.daily_orders.append(order_info)

    def _restore_state(self) -> None:
        assert self.state_manager is not None

        datas_dict: dict[str, Any] = {}
        if hasattr(self, "datas"):
            datas_dict = {data._name: data for data in self.datas}

        restore_strategy_state(self, self.state_manager)
        if hasattr(self, "broker"):
            restore_broker_state(self.broker, datas_dict, self.state_manager)
        if hasattr(self, "sr"):
            restore_sr_state(self.sr, self.state_manager)

        logger.info("State restoration complete")

    def _resubmit_previous_orders(self) -> None:
        assert self.state_manager is not None

        if self.daily_state_path is None:
            logger.warning("daily_state_path is None — cannot load orders")
            return

        last_date = self.state_manager.get_last_date()
        if last_date is None:
            logger.warning("No last_date in state — skipping order replay")
            return

        try:
            import pandas as pd

            date_str = pd.to_datetime(last_date).strftime("%Y%m%d")
        except (ValueError, TypeError):
            logger.debug("Date parse fallback for last_date=%s", last_date)
            date_str = str(last_date).replace("-", "")[:8]

        orders_file = os.path.join(self.daily_state_path, f"orders_{date_str}.pkl")
        if not os.path.exists(orders_file):
            logger.warning("Orders file not found: %s", orders_file)
            return

        with open(orders_file, "rb") as f:
            previous_orders: list[dict[str, Any]] = pickle.load(f)

        logger.info("Resubmitting %d previous orders from %s", len(previous_orders), orders_file)

        datas_dict: dict[str, Any] = {}
        if hasattr(self, "datas"):
            datas_dict = {data._name: data for data in self.datas}

        resubmitted = 0
        for order_info in previous_orders:
            order_type = order_info["order_type"]
            data_name = order_info.get("data_name")
            size = order_info.get("size")
            sr_info = order_info.get("sr", {})

            if data_name is None or data_name not in datas_dict:
                logger.warning("Data not found for resubmit: %s", data_name)
                continue

            data = datas_dict[data_name]
            kwargs: dict[str, Any] = {"data": data, "size": size, "sr": sr_info}

            exectype = order_info.get("exectype")
            price = order_info.get("price")
            if exectype is not None:
                kwargs["exectype"] = exectype
            if price is not None:
                kwargs["price"] = price

            try:
                order: Any = None
                is_close_all = bool(isinstance(sr_info, dict) and sr_info.get("close_all", False))

                if is_close_all:
                    import backtrader as bt

                    close_kwargs: dict[str, Any] = {"data": data, "sr": sr_info}
                    if size is not None:
                        close_kwargs["size"] = size
                    if "exectype" in kwargs:
                        close_kwargs["exectype"] = kwargs["exectype"]
                    if "price" in kwargs:
                        close_kwargs["price"] = kwargs["price"]
                    order = bt.Strategy.close(self, **close_kwargs)
                elif order_type == "buy" and hasattr(self, "buy"):
                    import backtrader as bt

                    order = bt.Strategy.buy(self, **kwargs)
                elif order_type == "sell" and hasattr(self, "sell"):
                    import backtrader as bt

                    order = bt.Strategy.sell(self, **kwargs)

                if order is not None:
                    order.created.dt = 1.0
                    resubmitted += 1
                    logger.info(
                        "Resubmitted %s %s size=%s close_all=%s",
                        order_type,
                        data_name,
                        size,
                        is_close_all,
                    )
                else:
                    logger.warning("Resubmit returned None: %s %s", order_type, data_name)
            except (KeyError, ValueError, AttributeError, RuntimeError):
                logger.exception("Failed to resubmit order: %s %s", order_type, data_name)

        logger.info("Order resubmit complete: %d/%d", resubmitted, len(previous_orders))

    def _save_daily_state(self, current_date: Any) -> None:
        assert self.daily_state_path is not None

        try:
            import pandas as pd

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

        sm.save_strategy_state(
            prev_dt=getattr(self, "prev_dt", None),
            init_position=getattr(self, "init_position", True),
            max_lever_rate=getattr(self, "max_lever_rate", 0.0),
            closed_daily_interest=getattr(self, "closed_daily_interest", 0.0),
            loss_total=getattr(self, "loss_total", 0),
            gain_total=getattr(self, "gain_total", 0),
            prev_total_value=getattr(self, "prev_total_value", None),
            prev_real_value=getattr(self, "prev_real_value", None),
            initial_cash=getattr(self, "initial_cash", None),
            prev_positions=getattr(self, "prev_positions", None),
        )

        if hasattr(self, "sr"):
            sr = self.sr
            sm.save_sr_state(
                size=getattr(sr, "size", {}),
                money=getattr(sr, "money", {}),
                apply_rate=getattr(sr, "apply_rate", {}),
                hold_days=getattr(sr, "hold_days", {}),
                open_price=getattr(sr, "open_price", {}),
                instrument_id_set=getattr(sr, "instrument_id_set", {}),
                exec_size=getattr(sr, "exec_size", {}),
            )

        sm.state["last_date"] = date_hyphen
        os.makedirs(self.daily_state_path, exist_ok=True)
        sm.save_to_file()
        logger.info("Daily state saved: %s", state_file)

    def _save_daily_orders(self, current_date: Any) -> None:
        assert self.daily_state_path is not None

        try:
            import pandas as pd

            date_str = pd.to_datetime(current_date).strftime("%Y%m%d")
        except (ValueError, TypeError):
            logger.debug("Date parse fallback for current_date=%s", current_date)
            date_str = str(current_date).replace("-", "")[:8]

        orders_file = os.path.join(self.daily_state_path, f"orders_{date_str}.pkl")
        os.makedirs(self.daily_state_path, exist_ok=True)

        with open(orders_file, "wb") as f:
            pickle.dump(self.daily_orders, f)

        logger.info("Daily orders saved: %s (%d orders)", orders_file, len(self.daily_orders))
        self.daily_orders = []
