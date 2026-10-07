
from __future__ import annotations


CLOSE_PRICE_QUERY = """\
SELECT * FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE date(datetime) = '{date}'
"""

CLOSE_PRICE_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, close
FROM ods.ods_quant_stock_marketdata_post_1day_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

OPEN_PRICE_QUERY = """\
SELECT instrument, open
FROM ods.ods_quant_stock_marketdata_post_1day_di
WHERE date(datetime) = toDate('{date}')
"""

OPEN_PRICE_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, open
FROM ods.ods_quant_stock_marketdata_post_1day_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

STOCK_RETURN_QUERY = """\
SELECT datetime, instrument, return_rate AS stock_return
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

STOCK_RETURN_SINGLE_QUERY = """\
SELECT datetime, instrument, return_rate AS stock_return
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime = '{date}'
"""

STOCK_TURNOVER_QUERY = """\
SELECT datetime, instrument, turnover
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

PERIOD_CLOSE_TURNOVER_QUERY = """\
SELECT datetime, instrument, close, total_turnover, turnover
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE date(datetime) >= '{start_date}' AND date(datetime) <= '{end_date}'
ORDER BY datetime
"""

PREVIOUS_TRADE_DAY_QUERY = """\
SELECT max(datetime) AS prev_date
FROM ods.ods_quant_stock_marketdata_post_1day_di
WHERE date(datetime) < '{date}'
"""

INDEX_CLOSE_QUERY = """\
SELECT instrument, close
FROM ods.ods_quant_stock_marketdata_index_1day_di
WHERE `datetime` = '{date}' AND instrument = '{idx_code}'
"""

INDEX_CLOSE_WALKBACK_QUERY = """\
SELECT instrument, close, `datetime`
FROM ods.ods_quant_stock_marketdata_index_1day_di
WHERE `datetime` <= '{date}' AND instrument = '{idx_code}'
ORDER BY `datetime` DESC
LIMIT {limit}
"""


PT_STOCK_QUERY = """\
SELECT DISTINCT Annoudt AS datetime, instrument, Chgtype
FROM ods.ods_quant_stock_csmar_SPT_Trdchg_di
WHERE (Chgtype LIKE '%X' OR Chgtype LIKE '%T' OR Chgtype LIKE 'TX')
AND (datetime <= '{date}')
"""

BASIS_INFO_QUERY = """\
SELECT *
FROM temp.temp_quant_stock_day_fut_other_BasisRatepercentile_zxhao_di
WHERE date(datetime) = '{date}'
"""

DOM_FUTURE_QUERY = """\
SELECT *
FROM ods.ods_quant_future_marketdata_dominant_di
WHERE date(datetime) = '{date}'
"""


SUSPEND_STOCKS_QUERY = """\
SELECT instrument
FROM dwd.dwd_quant_stock_fin_jydb_SuspendResumption_di
WHERE SuspendDate <= '{date}'
AND (ResumptionDate = '1900-01-01' OR ResumptionDate > '{date}')
"""


INDEX_WEIGHT_QUERY = """\
SELECT * FROM ods_quant_stock_marketdata_index_weight_di
WHERE datetime = '{date}' AND index = '{bench}'
"""

INDEX_WEIGHT_TIME_SERIES_QUERY = """\
SELECT * FROM ods_quant_stock_marketdata_index_weight_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
AND index = '{bench}'
"""

COMPONENT_CLASSIFICATION_QUERY = """\
SELECT instrument, is_300, is_500, is_1000, is_zz2000
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime = '{date}'
AND (is_300 = 1 OR is_500 = 1 OR is_1000 = 1 OR is_zz2000 = 1
     OR (is_300 = 0 AND is_500 = 0 AND is_1000 = 0 AND is_zz2000 = 0))
"""

COMPONENT_CLASSIFICATION_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, is_300, is_500, is_1000, is_zz2000
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

BARRA_INDEX_COMPONENT_QUERY = """\
SELECT instrument, is_300, is_500, is_1000
FROM dwd.dwd_quant_stock_marketdata_post_1day_di
WHERE datetime = '{date}'
"""


FACTOR_EXPOSURE_QUERY = """\
SELECT * FROM ods_quant_stock_marketdata_factor_exposure_di
WHERE datetime = '{date}'
"""

FACTOR_EXPOSURE_TIME_SERIES_QUERY = """\
SELECT * FROM ods_quant_stock_marketdata_factor_exposure_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

SPECIFIC_RISK_QUERY = """\
SELECT * FROM ods.ods_quant_stock_marketdata_specific_risk_di
WHERE datetime = '{date}'
"""

SPECIFIC_RETURN_QUERY = """\
SELECT datetime, instrument, return AS specific_return
FROM ods.ods_quant_stock_marketdata_specific_return_di
WHERE datetime = '{date}'
"""

SPECIFIC_RETURN_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, return AS specific_return
FROM ods.ods_quant_stock_marketdata_specific_return_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

FACTOR_RETURN_QUERY = """\
SELECT * FROM ods.ods_quant_stock_marketdata_factor_return_di
WHERE date(datetime) = '{date}'
"""

FACTOR_RETURN_TIME_SERIES_QUERY = """\
SELECT * FROM ods.ods_quant_stock_marketdata_factor_return_di
WHERE date(datetime) >= '{start_date}' AND date(datetime) <= '{end_date}'
"""

FACTOR_QUINTILE_QUERY = """\
SELECT instrument, {factor_name}
FROM ods_quant_stock_marketdata_factor_exposure_di
WHERE datetime = '{date}'
AND {factor_name} IS NOT NULL
"""

FACTOR_QUINTILE_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, {factor_name}
FROM ods_quant_stock_marketdata_factor_exposure_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
AND {factor_name} IS NOT NULL
"""


STOCK_SIZE_QUERY = """\
SELECT instrument, circ_market_cap AS size
FROM dwd.dwd_quant_stock_wind_fin_shares_di
WHERE datetime = '{date}'
"""

VALUE_PB_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, valu_pb
FROM temp_factors.temp_quant_stock_multi_fin_valu_relative_valuation_factors_jnqiu_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

VALUE_SP_TTM_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, valu_sp_ttm
FROM temp_factors.temp_quant_stock_multi_fin_valu_relative_valuation_factors_jnqiu_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""

WEST_EP_FTM_TIME_SERIES_QUERY = """\
SELECT datetime, instrument, west_ep_FTM
FROM temp_factors.temp_quant_stock_multi_fin_west_fundamental_valuation_reciprocal_factors_benchmark_di
WHERE datetime >= '{start_date}' AND datetime <= '{end_date}'
"""


LIQUIDITY_FILTER_QUERY = """\
WITH pool AS (
    SELECT
        a.instrument AS instrument,
        a.datetime AS datetime,
        rank_buyvol,
        rank_vol,
        rank_turnover,
        is_event_accepted_v3,
        is_suspended
    FROM dwd.dwd_quant_stock_marketdata_post_1day_di a
    JOIN temp_factors_st.temp_quant_stock_multi_alt_news_risk_event_accepted_v3_benchmark_di b
        ON a.instrument = b.instrument AND a.datetime = b.datetime
    JOIN temp_factors_st.temp_quant_stock_lvl2_vop_liqu_liquidity_zhxiao_di c
        ON a.instrument = c.instrument AND a.datetime = c.datetime
    JOIN temp_factors_st.temp_quant_stock_day_vop_liqu_liquidity_zhxiao_di d
        ON a.instrument = d.instrument AND a.datetime = d.datetime
)
SELECT instrument FROM pool
WHERE datetime = '{dt}'
    AND is_event_accepted_v3 = True
    AND is_suspended = False
    AND (rank_buyvol > 0.5 OR rank_vol > 0.5 OR rank_turnover > 0.5)
"""

LIQUIDITY_FILTER_EVENT_ONLY_QUERY = """\
WITH pool AS (
    SELECT
        a.instrument AS instrument,
        a.datetime AS datetime,
        is_event_accepted_v3
    FROM dwd.dwd_quant_stock_marketdata_post_1day_di a
    JOIN temp_factors_st.temp_quant_stock_multi_alt_news_risk_event_accepted_v3_benchmark_di b
        ON a.instrument = b.instrument AND a.datetime = b.datetime
    JOIN temp_factors_st.temp_quant_stock_lvl2_vop_liqu_liquidity_zhxiao_di c
        ON a.instrument = c.instrument AND a.datetime = c.datetime
    JOIN temp_factors_st.temp_quant_stock_day_vop_liqu_liquidity_zhxiao_di d
        ON a.instrument = d.instrument AND a.datetime = d.datetime
)
SELECT instrument FROM pool
WHERE datetime = '{dt}'
    AND is_event_accepted_v3 = True
"""
