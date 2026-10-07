
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quant_pro.infrastructure.clickhouse import queries as Q

logger = logging.getLogger(__name__)


class IndexDataFetcher:

    def __init__(self, client: Any) -> None:
        self.client = client


    def get_index_weight(self, date: str, bench: str) -> pd.DataFrame:
        sql = Q.INDEX_WEIGHT_QUERY.format(date=date, bench=bench)
        result: pd.DataFrame = self.client.query(sql)
        result.drop(["index"], axis=1, inplace=True)
        result["datetime"] = pd.to_datetime(result["datetime"])
        return result

    def get_index_weight_time_series(
        self, start_date: str, end_date: str, bench: str
    ) -> pd.DataFrame:
        sql = Q.INDEX_WEIGHT_TIME_SERIES_QUERY.format(
            start_date=start_date, end_date=end_date, bench=bench
        )
        result: pd.DataFrame = self.client.query(sql)
        result.drop(["index"], axis=1, inplace=True)
        result["datetime"] = pd.to_datetime(result["datetime"])
        return result


    def get_index_component(self, date: str, bench: str) -> list[str]:
        result = self.get_index_weight(date, bench)
        return list(result["instrument"].tolist())


    def get_component_classification(self, date: str) -> pd.DataFrame:
        sql = Q.COMPONENT_CLASSIFICATION_QUERY.format(date=date)
        component_df: pd.DataFrame = self.client.query(sql)
        if component_df.empty:
            return pd.DataFrame(columns=["instrument", "component_type"])

        def _classify(row: pd.Series[Any]) -> str:
            if row["is_300"] == 1:
                return "CSI300"
            if row["is_500"] == 1:
                return "CSI500"
            if row["is_1000"] == 1:
                return "CSI1000"
            if row["is_zz2000"] == 1:
                return "CSI2000"
            return "Other"

        component_df["component_type"] = component_df.apply(_classify, axis=1)
        return component_df[["instrument", "component_type"]]

    def get_component_classification_time_series(
        self, start_date: str, end_date: str
    ) -> pd.DataFrame:
        sql = Q.COMPONENT_CLASSIFICATION_TIME_SERIES_QUERY.format(
            start_date=start_date, end_date=end_date
        )
        component_df: pd.DataFrame = self.client.query(sql)
        component_df["datetime"] = component_df["datetime"].astype(str)
        if component_df.empty:
            return pd.DataFrame(columns=["datetime", "instrument", "component_type"])

        def _classify(row: pd.Series[Any]) -> str:
            if row["is_300"] == 1:
                return "CSI300"
            if row["is_500"] == 1:
                return "CSI500"
            if row["is_1000"] == 1:
                return "CSI1000"
            if row["is_zz2000"] == 1:
                return "CSI2000"
            return "Other"

        component_df["component_type"] = component_df.apply(_classify, axis=1)
        return component_df[
            [
                "datetime",
                "instrument",
                "is_300",
                "is_500",
                "is_1000",
                "is_zz2000",
                "component_type",
            ]
        ]


    def get_component_exposure(self, date: str) -> pd.DataFrame:
        component_df = self.get_component_classification(date)
        if component_df.empty:
            return pd.DataFrame()

        component_types = ["CSI300", "CSI500", "CSI1000", "CSI2000", "Other"]
        exposure_data = []
        for _, row in component_df.iterrows():
            exposure_row: dict[str, Any] = {"instrument": row["instrument"]}
            for ct in component_types:
                exposure_row[ct] = 1 if row["component_type"] == ct else 0
            exposure_data.append(exposure_row)
        exposure_df = pd.DataFrame(exposure_data)
        return exposure_df.set_index("instrument")

    def get_component_exposure_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        component_df = self.get_component_classification_time_series(start_date, end_date)
        if component_df.empty:
            return pd.DataFrame()
        component_df.rename(
            columns={
                "is_300": "CSI300",
                "is_500": "CSI500",
                "is_1000": "CSI1000",
                "is_zz2000": "CSI2000",
            },
            inplace=True,
        )
        component_df["Other"] = (
            1
            - component_df["CSI300"]
            - component_df["CSI500"]
            - component_df["CSI1000"]
            - component_df["CSI2000"]
        ) > 0
        return component_df[
            ["datetime", "instrument", "CSI300", "CSI500", "CSI1000", "CSI2000", "Other"]
        ]


    def get_barra_index_component(self, date: str) -> pd.DataFrame:
        sql = Q.BARRA_INDEX_COMPONENT_QUERY.format(date=date)
        component: pd.DataFrame = self.client.query(sql)
        index_cols = ["is_300", "is_500", "is_1000"]
        component[index_cols] = component[index_cols].astype(int)
        return component
