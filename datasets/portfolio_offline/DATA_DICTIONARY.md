# Offline portfolio inputs

English · [中文](DATA_DICTIONARY-zh_CN.md)

Paths are relative to this directory.

| Input | Path | Purpose |
|---|---|---|
| Enhanced-index scores | `data/scores/enhanced_index/xgb_v6_ei2000_single_s3r59.feather` | Per-stock prediction scores used as expected-return proxies. |
| Long-short scores | `src/quant_pro/resources/gurobi_mip_soc/default_xgbv6_zscore_p300_cap015/xgb_v6_ei2000_single_s3r59_daily_zscore.feather` | Daily cross-sectional standardized scores. |
| Hedged-stock scores | `data/scores/neutral/xgb_rolling_comb_neu500_21_static_daily.feather` | Daily scores for the stock leg of the futures-hedged portfolio. |
| Trading calendar | `data/snapshot/calendar.csv` | Trading dates and next/previous-session lookup. |
| Query replay | `data/snapshot/clickhouse_queries/` | Recorded market, index, factor and suspension query results. |
| Data-fetcher replay | `data/snapshot/optimizer_fetcher_calls/` | Recorded optimizer data-access results. |
| Historical range tables | `data/snapshot/canonical_range/` | Factor exposure, factor return, specific return and price/turnover histories. |
| Daily market factors | `data/snapshot/factors/day/` | Stock OHLCV, turnover, price limits and tradability indicators. |
| Index factors | `data/snapshot/factors/index_day/` | Daily index OHLCV and turnover. |
| Futures factors | `data/snapshot/factors/future_day/` | Futures prices, expiry, volume, open interest, multiplier and margin rates. |
| Risk covariance | `data/risk_factor_covariance/YYYY-MM-DD` | Daily style/industry factor covariance matrices. |
| Borrow supply | `data/market/merged_bonds_240301_251225.csv` | Dated stock-borrow availability, rates and slip identifiers. |

Each replay directory contains `index.json`, which maps readable sequential IDs such as `replay_00001` to an exact function name and argument representation. The matching pickle stores the recorded return value. This index is required for offline lookup and date filtering. Missing calls fail locally; the benchmark does not query remote databases.

Optimizer bounds and reference settings are in `configs/optimizers/` and the long-short resource directory. `config.yaml` provides shared industry definitions and runtime configuration. Split dates and scoring calibration constants are maintained in the repository's `.asof/split_*.json` contracts. Runtime date views and month caches are generated when needed.
