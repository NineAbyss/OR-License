#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyProfile:
    key: str
    benchmark: str
    score_relative: str
    entry_module: str
    tuning_env: str
    long_only: bool
    needs_borrow: bool
    label: str


ENHANCED_INDEX = StrategyProfile(
    key="enhanced_index",
    benchmark="IN932000",
    score_relative="data/scores/enhanced_index/xgb_v6_ei2000_single_s3r59.feather",
    entry_module="quant_pro.entry.enhanced_index_backtest",
    tuning_env="ORLE_EI_TUNING_YAML",
    long_only=True,
    needs_borrow=False,
    label="中证2000增强",
)

LONGSHORT = StrategyProfile(
    key="longshort",
    benchmark="IN000905",
    score_relative=(
        "src/quant_pro/resources/gurobi_mip_soc/default_xgbv6_zscore_p300_cap015"
        "/xgb_v6_ei2000_single_s3r59_daily_zscore.feather"
    ),
    entry_module="quant_pro.entry.longshort_backtest",
    tuning_env="ORLE_LS_TUNING_YAML",
    long_only=False,
    needs_borrow=True,
    label="市场中性多空",
)

SIF = StrategyProfile(
    key="sif",
    benchmark="IN000905",
    score_relative="data/scores/neutral/xgb_rolling_comb_neu500_21_static_daily.feather",
    entry_module="quant_pro.entry.single_sif_beta0_next_month_backtest",
    tuning_env="ORLE_SIF_TUNING_YAML",
    long_only=True,
    needs_borrow=False,
    label="股指期货对冲多头",
)

PROFILES = {
    profile.key: profile for profile in (ENHANCED_INDEX, LONGSHORT, SIF)
}
DEFAULT_PROFILE = ENHANCED_INDEX.key


def get(key: str | None) -> StrategyProfile:
    resolved = key or DEFAULT_PROFILE
    if resolved not in PROFILES:
        raise SystemExit(
            f"unknown strategy profile {resolved!r}; expected one of {sorted(PROFILES)}"
        )
    return PROFILES[resolved]
