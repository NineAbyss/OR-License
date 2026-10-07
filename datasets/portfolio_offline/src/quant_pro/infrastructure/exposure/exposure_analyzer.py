
from __future__ import annotations

from typing import Any

import pandas as pd

DEFAULT_INDUSTRY_FACTORS: list[str] = [
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
]

DEFAULT_STYLE_FACTORS: list[str] = [
    "momentum",
    "beta",
    "book_to_price",
    "earnings_yield",
    "liquidity",
    "size",
    "residual_volatility",
    "comovement",
    "leverage",
    "growth",
    "dividend_yield",
    "earnings_quality",
    "earnings_variability",
    "investment_quality",
    "longterm_reversal",
    "mid_cap",
    "profitability",
]


class ExposureAnalyzer:

    def __init__(
        self,
        data_fetcher: Any,
        industry_factors: list[str] | None = None,
        style_factors: list[str] | None = None,
        bench: str = "IN000852",
    ) -> None:
        self.data_fetcher = data_fetcher
        self.industry_factors = industry_factors or DEFAULT_INDUSTRY_FACTORS
        self.style_factors = style_factors or DEFAULT_STYLE_FACTORS
        self.total_factors = self.industry_factors + self.style_factors
        self.bench = bench


    def get_exposure(self, date: str, portfolio: pd.DataFrame) -> pd.DataFrame:
        portfolio = portfolio[["instrument", "weight"]].copy()
        factor_exposure_today = self.data_fetcher.get_factor_exposure_today(date)
        available_factors = [f for f in self.total_factors if f in factor_exposure_today.columns]
        factor_exposure_today = factor_exposure_today[["instrument"] + available_factors]

        portfolio_exposure = pd.merge(portfolio, factor_exposure_today, on="instrument", how="left")
        portfolio_exposure = portfolio_exposure[["instrument", "weight"] + available_factors]
        return portfolio_exposure

    def get_index_portfolio(self, date: str, bench: str | None = None) -> pd.DataFrame:
        if bench is None:
            bench = self.bench
        return self.data_fetcher.get_index_weight(date, bench)

    def get_index_sum_exposure_longshort(
        self,
        bench: str,
        date: str,
    ) -> tuple[pd.DataFrame, Any]:
        if not bench:
            bench = self.bench

        index_portfolio = self.get_index_portfolio(date, bench)
        index_portfolio.dropna(inplace=True)
        exposure = self.get_exposure(date, index_portfolio)

        nan_instruments = exposure[exposure.isna().any(axis=1)]["instrument"].tolist()
        exposure.dropna(inplace=True)
        index_portfolio = index_portfolio[~index_portfolio["instrument"].isin(nan_instruments)]
        exposure.reset_index(drop=True, inplace=True)
        index_portfolio.reset_index(drop=True, inplace=True)

        exposure_whole = exposure
        weight = exposure["weight"]
        exposure_factors = exposure.drop(columns=["instrument", "weight"])
        sum_exposure = exposure_factors.multiply(weight, axis=0).sum(axis=0)

        return exposure_whole, sum_exposure
