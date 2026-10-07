
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quant_pro.infrastructure.calendar import factor_client_adapter
from quant_pro.infrastructure.clickhouse import queries as Q

logger = logging.getLogger(__name__)


class FactorDataFetcher:

    def __init__(self, client: Any) -> None:
        self.client = client


    def get_factor_exposure(self, date: str) -> pd.DataFrame:
        sql = Q.FACTOR_EXPOSURE_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)

        if result.empty:
            previous_date: str = factor_client_adapter.get_previous_trade_day(date)
            sql = Q.FACTOR_EXPOSURE_QUERY.format(date=previous_date)
            result = self.client.query(sql)
            if result.empty:
                raise ValueError(
                    f"因子暴露数据缺失：日期 {date} 和前一交易日 {previous_date} 均无数据"
                )
            logger.warning(
                "日期 %s 的因子暴露数据缺失，使用前一交易日 %s 的数据",
                date,
                previous_date,
            )

        result.index = result["instrument"]
        result.drop(["datetime", "instrument"], axis=1, inplace=True)
        return result

    def get_factor_exposure_today(self, date: str) -> pd.DataFrame:
        sql = Q.FACTOR_EXPOSURE_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result.drop(["datetime"], axis=1, inplace=True)
        return result

    def get_factor_exposure_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        prev_trading_date: str = factor_client_adapter.get_previous_trade_day(start_date)
        sql = Q.FACTOR_EXPOSURE_TIME_SERIES_QUERY.format(
            start_date=str(prev_trading_date), end_date=end_date
        )
        res: pd.DataFrame = self.client.query(sql)
        res = (
            res.set_index(["datetime", "instrument"])
            .sort_values(by="datetime", ascending=True)
            .groupby("instrument")
            .shift(1)
            .reset_index()
        )
        res["datetime"] = res["datetime"].astype(str)
        res = res[res["datetime"] != str(prev_trading_date)]
        return res


    def get_factor_covariance(self, date: str) -> pd.DataFrame:
        result: pd.DataFrame = pd.read_csv(
            f"data/risk_factor_covariance/{date}", index_col="index"
        )
        result.index.name = None
        return result



    def get_specific_risk(self, date: str) -> pd.DataFrame:
        sql = Q.SPECIFIC_RISK_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result.index = result["instrument"]
        result.drop(["datetime", "instrument"], axis=1, inplace=True)
        return result


    def get_factor_return(self, date: str) -> pd.DataFrame:
        sql = Q.FACTOR_RETURN_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result.drop(columns=["datetime"])

    def get_factor_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.FACTOR_RETURN_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        return self.client.query(sql)


    def get_factor_quintile_classification(
        self, date: str, factor_name: str = "momentum"
    ) -> pd.DataFrame:
        sql = Q.FACTOR_QUINTILE_QUERY.format(date=date, factor_name=factor_name)
        factor_df: pd.DataFrame = self.client.query(sql)
        if factor_df.empty:
            return pd.DataFrame(columns=["instrument", "quintile_group"])

        factor_df = factor_df.sort_values(factor_name, ascending=False)
        total = len(factor_df)
        qsize = total // 5 if total else 0
        groups: list[dict[str, Any]] = []
        for i, (_, row) in enumerate(factor_df.iterrows()):
            if i < qsize:
                group = "Q1"
            elif i < 2 * qsize:
                group = "Q2"
            elif i < 3 * qsize:
                group = "Q3"
            elif i < 4 * qsize:
                group = "Q4"
            else:
                group = "Q5"
            groups.append({"instrument": row["instrument"], "quintile_group": group})
        return pd.DataFrame(groups)[["instrument", "quintile_group"]]

    def get_factor_quintile_classification_time_series(
        self,
        start_date: str,
        end_date: str,
        factor_name: str = "momentum",
    ) -> pd.DataFrame:
        sql = Q.FACTOR_QUINTILE_TIME_SERIES_QUERY.format(
            start_date=start_date, end_date=end_date, factor_name=factor_name
        )
        factor_df: pd.DataFrame = self.client.query(sql)
        factor_df["datetime"] = pd.to_datetime(factor_df["datetime"]).dt.strftime("%Y-%m-%d")
        if factor_df.empty:
            return pd.DataFrame(columns=["datetime", "instrument", "quintile_group"])
        factor_df = factor_df.sort_values(
            ["datetime", factor_name], ascending=[True, False]
        ).reset_index(drop=True)
        quintile_groups = (
            factor_df.groupby("datetime")
            .apply(lambda x: pd.qcut(x[factor_name], 5, labels=False), include_groups=False)
            .reset_index(level="datetime")
        )
        factor_df["quintile_group"] = quintile_groups[factor_name].apply(lambda x: f"Q{x + 1}")
        return factor_df[["datetime", "instrument", "quintile_group"]]


    def get_factor_quintile_exposure(
        self, date: str, factor_name: str = "momentum"
    ) -> pd.DataFrame:
        quintile_df = self.get_factor_quintile_classification(date, factor_name)
        if quintile_df.empty:
            return pd.DataFrame()
        exposure_data: list[dict[str, Any]] = []
        for _, row in quintile_df.iterrows():
            exposure_row: dict[str, Any] = {"instrument": row["instrument"]}
            for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
                exposure_row[q] = 1 if row["quintile_group"] == q else 0
            exposure_data.append(exposure_row)
        return pd.DataFrame(exposure_data).set_index("instrument")

    def get_factor_quintile_exposure_time_series(
        self,
        start_date: str,
        end_date: str,
        factor_name: str = "momentum",
    ) -> pd.DataFrame:
        quintile_df = self.get_factor_quintile_classification_time_series(
            start_date, end_date, factor_name
        )
        if quintile_df.empty:
            return pd.DataFrame()
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            quintile_df[q] = quintile_df["quintile_group"] == q
        return quintile_df
