from types import MethodType
import pandas as pd


def optimize_agent_target(self, pred, bond, total_value, position=None,
                          bond_table=None, **kwargs):

    current_date = self._date_from_pred(pred, kwargs.pop("current_date", None))
    kwargs.pop("margin_rate", None)
    beta_exposure = kwargs.pop("beta_exposure", None)
    benchmark_weights = kwargs.pop("benchmark_weights", None)
    if position is not None:
        position = position.copy()
        position["weight"] = (
            pd.to_numeric(position["volume"], errors="raise")
            * pd.to_numeric(position["close"], errors="raise")
            / float(total_value)
        )
        kwargs["position"] = position
        kwargs["bond_table"] = bond_table
    target = self.stock_optimizer.optimize(pred, bond, total_value, **kwargs)
    if target is None:
        self.last_hedge_result = None
        return None
    if "agent_ic_hedge" not in target.attrs or "agent_stock_fraction" not in target.attrs:
        raise ValueError("validated SIF target lacks submitted stock and IC allocation")
    stock_value = float(total_value) * float(target.attrs["agent_stock_fraction"])
    return self._finish(
        target, current_date=current_date, stock_value=stock_value,
        short_cash=float(total_value) - stock_value, short_notional=stock_value,
        beta_exposure=beta_exposure, benchmark_weights=benchmark_weights,
    )


def finish_agent_target(self, stock_weights, *, current_date, stock_value,
                        short_cash, short_notional, beta_exposure, benchmark_weights):
    if stock_weights is None:
        self.last_hedge_result = None
        return None
    from quant_pro.adapters.optimizers.dailyhigh import DailyHighHedgeResult
    submitted = stock_weights.attrs.get('agent_ic_hedge')
    if submitted is None:
        state = self.engine.state
        contract = getattr(state, "current_future", None)
        if not contract:
            raise RuntimeError("cannot hold previous SIF hedge before initialization")
        prior_notional = float(getattr(state, "short_value_after_beta", 0.0) or 0.0)
        prices = self.engine.future_data_fetcher.get_all_future_close_prices(
            current_date, ["IC"]
        )
        liquidity = self.engine.future_data_fetcher.get_future_volume_interest_multiplier(
            current_date, ["IC"]
        )
        selected_price = (
            prices.loc[prices.future.astype(str) == str(contract)]
            if "future" in prices.columns
            else prices.loc[[contract]] if contract in prices.index else prices.iloc[0:0]
        )
        selected_liquidity = (
            liquidity.loc[liquidity.future.astype(str) == str(contract)]
            if "future" in liquidity.columns
            else liquidity.loc[[contract]] if contract in liquidity.index else liquidity.iloc[0:0]
        )
        if selected_price.empty or selected_liquidity.empty:
            raise RuntimeError(f"cannot price held SIF hedge {contract!r}")
        price = float(selected_price.iloc[0]["price"])
        multiplier = float(selected_liquidity.iloc[0]["multiplier"])
        prior_price = float(getattr(state, "last_close_price", 0.0) or 0.0)
        sizing_price = prior_price if prior_price > 0 else price
        hands = int(round(prior_notional / (sizing_price * multiplier))) if sizing_price * multiplier else 0
        submitted = {"future": str(contract), "contract_size": max(hands, 0)}
        stock_weights.attrs["agent_ic_hedge"] = submitted
    contract = str(submitted['future'])
    hands = int(submitted['contract_size'])
    data = self.engine.future_data_fetcher
    prices = data.get_all_future_close_prices(current_date, ['IC'])
    liquidity = data.get_future_volume_interest_multiplier(current_date, ['IC'])
    price_rows = prices.loc[prices.future.astype(str) == contract]
    if price_rows.empty:
        raise RuntimeError(f"cannot price SIF hedge {contract!r}")
    price = float(price_rows.iloc[0]['price'])
    if "future" in liquidity.columns:
        liquidity_rows = liquidity.loc[liquidity.future.astype(str) == contract]
    else:
        liquidity_rows = liquidity.loc[[contract]] if contract in liquidity.index else liquidity.iloc[0:0]
    if liquidity_rows.empty:
        raise RuntimeError(f"cannot resolve multiplier for SIF hedge {contract!r}")
    multiplier = float(liquidity_rows.iloc[0]['multiplier'])
    state = self.engine.state
    if state.current_future != contract:
        state.last_change_day = pd.Timestamp(current_date)
    state.current_future = contract
    state.last_close_price = price
    state.short_value_after_beta = hands * price * multiplier
    effective_stock_value = stock_value
    state.portfolio_benchmark_beta_rate = (state.short_value_after_beta / effective_stock_value
                                          if effective_stock_value else 0.)
    self.last_hedge_result = DailyHighHedgeResult(
        benchmark='IN000905', spot_index='IN399905', future_family='IC',
        contract=contract, contract_size=hands, stock_value=effective_stock_value,
        short_cash=short_cash,
        short_value_after_beta=state.short_value_after_beta,
        beta_rate=state.portfolio_benchmark_beta_rate)
    return stock_weights


def install_agent_execution(optimizer):
    optimizer.agent_controls_hedge = True
    optimizer.optimize = MethodType(optimize_agent_target, optimizer)
    optimizer._finish = MethodType(finish_agent_target, optimizer)


class SubmittedSIFOptimizer:
    def __init__(self, future_data, tuning_params_list, state=None):
        from types import SimpleNamespace
        from quant_pro.adapters.optimizers.dailyhigh import BenchmarkFutureSpec, DailyHighState
        self.engine = SimpleNamespace(
            spec=BenchmarkFutureSpec("IN000905", "IN399905", "IC"),
            future_data_fetcher=future_data,
            state=state if state is not None else DailyHighState(),
        )
        self.tuning_params_list = tuning_params_list
        self.last_hedge_result = None

    @property
    def state(self):
        return self.engine.state

    def set_tuning_params_list(self, params):
        self.tuning_params_list = params
        setter = getattr(self.stock_optimizer, "set_tuning_params_list", None)
        if callable(setter):
            setter(params)

    @staticmethod
    def _date_from_pred(pred, explicit=None):
        if explicit is not None:
            return pd.Timestamp(explicit)
        frame = pred[0] if isinstance(pred, list) else pred
        if not isinstance(frame, pd.DataFrame) or "datetime" not in frame.columns or frame.empty:
            raise ValueError("current_date is required when pred has no datetime rows")
        return pd.Timestamp(frame.iloc[-1]["datetime"])
