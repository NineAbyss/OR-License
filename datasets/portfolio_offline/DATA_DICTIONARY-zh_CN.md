# 离线投资组合输入

[English](DATA_DICTIONARY.md) · 中文

路径相对于本目录。

| 输入 | 路径 | 用途 |
|---|---|---|
| 指数增强评分 | `data/scores/enhanced_index/xgb_v6_ei2000_single_s3r59.feather` | 每只股票的预测评分，作为预期收益的代理。 |
| 多空评分 | `src/quant_pro/resources/gurobi_mip_soc/default_xgbv6_zscore_p300_cap015/xgb_v6_ei2000_single_s3r59_daily_zscore.feather` | 每日横截面标准化后的评分。 |
| 对冲股票评分 | `data/scores/neutral/xgb_rolling_comb_neu500_21_static_daily.feather` | 期货对冲组合中股票端的每日评分。 |
| 交易日历 | `data/snapshot/calendar.csv` | 交易日，以及前一个/后一个交易日的查找。 |
| 查询回放 | `data/snapshot/clickhouse_queries/` | 记录下来的行情、指数、因子和停牌查询结果。 |
| 数据获取回放 | `data/snapshot/optimizer_fetcher_calls/` | 记录下来的优化器数据访问结果。 |
| 历史区间表 | `data/snapshot/canonical_range/` | 因子暴露、因子收益、特异收益以及价格/换手率历史。 |
| 每日行情因子 | `data/snapshot/factors/day/` | 股票 OHLCV、换手率、涨跌停价和可交易标记。 |
| 指数因子 | `data/snapshot/factors/index_day/` | 指数每日 OHLCV 和换手率。 |
| 期货因子 | `data/snapshot/factors/future_day/` | 期货价格、到期日、成交量、持仓量、合约乘数和保证金率。 |
| 风险协方差 | `data/risk_factor_covariance/YYYY-MM-DD` | 每日风格/行业因子协方差矩阵。 |
| 融券供给 | `data/market/merged_bonds_240301_251225.csv` | 按日期记录的可融券数量、费率和券单编号。 |

每个回放目录都包含 `index.json`，它把 `replay_00001` 这样可读的顺序编号映射到精确的函数名和参数表示，对应的 pickle 文件保存记录下来的返回值。离线查找和日期过滤都需要这个索引。缺失的调用会在本地直接失败，评测不会查询远程数据库。

优化器的边界和参考设置在 `configs/optimizers/` 和多空资源目录中。`config.yaml` 提供共享的行业定义和运行时配置。划分日期和评分校准常数保存在仓库的 `.asof/split_*.json` 合同中。运行时日期视图和月度缓存会在需要时生成。
