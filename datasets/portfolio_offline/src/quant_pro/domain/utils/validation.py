
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


INDEX_LAUNCH_DATES: dict[str, str] = {
    "IN932000": "2023-08-31",
    "IN000300": "2008-01-02",
    "IN000905": "2008-01-02",
    "IN000852": "2014-10-31",
    "IN866006": "2015-12-31",
    "IN000922": "2008-05-30",
}

INDEX_NAMES: dict[str, str] = {
    "IN932000": "中证2000",
    "IN000300": "沪深300",
    "IN000905": "中证500",
    "IN000852": "中证1000",
    "IN866006": "微盘股指数",
    "IN000922": "红利指数",
}


def validate_index_launch_date(current_date: str, benchmark: str) -> None:
    if benchmark not in INDEX_LAUNCH_DATES:
        logger.warning("未知的指数代码 %s，跳过上市日期检查", benchmark)
        return

    launch_date = INDEX_LAUNCH_DATES[benchmark]
    index_name = INDEX_NAMES.get(benchmark, benchmark)

    if current_date < launch_date:
        error_msg = (
            f"错误: 回测日期 {current_date} 早于 {index_name}({benchmark}) "
            f"的上市日期 {launch_date}！\n"
            f"   {index_name} 于 {launch_date} 正式上市，无法在此之前进行回测。\n"
            f"   请调整回测开始日期至 {launch_date} 之后。"
        )
        raise ValueError(error_msg)

    logger.info(
        "指数日期检查通过: %s(%s) 上市日期 %s，当前回测日期 %s",
        index_name,
        benchmark,
        launch_date,
        current_date,
    )
