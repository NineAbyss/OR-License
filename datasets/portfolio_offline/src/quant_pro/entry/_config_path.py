
from __future__ import annotations

import os


def default_backtest_config_path() -> str:
    return (
        os.environ.get("QUANT_PRO_DB_CONFIG")
        or os.environ.get("BACKTESTER_CONFIG")
        or "config.yaml"
    )


def sync_backtester_config(config_path: str) -> str:
    os.environ["BACKTESTER_CONFIG"] = config_path
    return config_path
