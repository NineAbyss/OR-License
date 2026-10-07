
from __future__ import annotations

import logging
from functools import reduce
from typing import Any

import pandas as pd

from quant_pro.infrastructure.redis.client import RedisClient

logger = logging.getLogger(__name__)


class RedisDataFetcher:

    def __init__(self, client: RedisClient) -> None:
        if not isinstance(client, RedisClient):
            raise ValueError("client must be an instance of RedisClient")
        self._db_client = client


    def get_weight(
        self,
        hash_keys_and_counts: list[tuple[str, int]] | None = None,
    ) -> pd.DataFrame:
        if hash_keys_and_counts is None:
            hash_keys_and_counts = [("list_predict_5", 3)]

        raw_frames: list[pd.DataFrame] = []
        for hash_key, count in hash_keys_and_counts:
            raw_frames.extend(self._db_client.fetch_list_dataframes(hash_key=hash_key, count=count))

        if not raw_frames:
            raise ValueError(
                f"打分来源 {hash_keys_and_counts} 未返回任何数据帧，请检查 Redis 数据完整性。"
            )

        target_date = pd.to_datetime(raw_frames[0]["target_time"].iloc[0]).date()

        id_sets = [set(df["SecurityID"]) for df in raw_frames]
        common_ids: set[Any] = reduce(lambda a, b: a.intersection(b), id_sets)
        if not common_ids:
            raise ValueError(
                f"打分来源 {hash_keys_and_counts} 的 SecurityID 交集为空，请检查数据完整性。"
            )

        filtered_dfs = [
            df[df["SecurityID"].isin(common_ids)][["SecurityID", "label"]].copy()
            for df in raw_frames
        ]
        combined = pd.concat(filtered_dfs, ignore_index=True)
        scores = combined.groupby("SecurityID")["label"].mean().reset_index()
        scores.rename(columns={"label": "score"}, inplace=True)

        parts = scores["SecurityID"].str.split(".", expand=True)
        out = pd.DataFrame(
            {
                "datetime": target_date,
                "instrument": parts[1] + parts[0],
                "score": scores["score"].values,
            }
        )
        return out[["datetime", "instrument", "score"]]


    def get_available_fund(self, account: str = "offline_account") -> float:
        res = self._db_client.fetch_dict("asset", account)
        if account in res:
            res = res[account]
        if res and "available_fund" in res:
            return float(res["available_fund"])
        raise ValueError(f"Available fund not found for account {account}: {res}")

    def get_position(self, account: str = "offline_account") -> pd.DataFrame:
        position_df = self._db_client.fetch_dataframe(f"position_{account}")
        if position_df is None:
            raise ValueError(f"No position data for account {account}")
        quote_df = self._db_client.fetch_dataframe("joine_min_k_stream")
        if quote_df is None:
            raise ValueError("No quote data in joine_min_k_stream")
        quote_df = quote_df[["SecurityID", "close"]]

        merged = pd.merge(
            position_df, quote_df, left_on="symbol", right_on="SecurityID", how="left"
        )
        if merged["close"].isnull().any():
            missing = merged[merged["close"].isnull()]["symbol"].tolist()
            raise ValueError(
                f"匹配失败：position_{account} 中的 symbol {missing} "
                "在 joine_min_k_stream 中没有找到。"
            )
        merged.drop(columns=["SecurityID"], inplace=True)

        parts = merged["symbol"].str.split(".", expand=True)
        result = pd.DataFrame(
            {
                "stockcode": parts[1] + parts[0],
                "volume": merged["holding_qty"].values,
                "tradeable_qty": merged["tradeable_qty"].values,
                "close": merged["close"].values,
            }
        )
        return result
